"""
插件方法
"""

import asyncio
from typing import Annotated, Any, Dict, List, Optional, Set, Tuple
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import logger
from nekro_agent.services.plugin.base import SandboxMethodType
from nekro_agent.services.command.base import CommandPermission
from nekro_agent.services.command.ctl import CmdCtl
from nekro_agent.services.command.schemas import (
    Arg,
    CommandExecutionContext,
    CommandResponse,
)
from .mem0_output_formatter import (
    format_add_output,
    format_get_all_output,
    format_history_output,
    format_history_text,
    format_search_output,
    normalize_results,
    _format_memory_list,
    _get_combined_score,
)
from .mem0_utils import get_mem0_client
from .plugin import get_memory_config, plugin
from .utils import MemoryScope, decode_id, get_preset_id, resolve_memory_scope
from nekro_agent.models.db_chat_message import DBChatMessage
from .pre_search_utils import build_pre_search_query, convert_db_messages_to_dict
from .dedup_simhash import SimHasher, hamming_distance_hex
from .dedup_similarity import calculate_similarity
from .query_rewrite import should_skip_retrieval
from .extraction_prompts import ENHANCED_MEMORY_PROMPT
from .extraction_parser import parse_extracted_memories
from .memory_engine_router import route_search


_MIGRATION_IN_FLIGHT: Set[Tuple[Optional[str], Optional[str], Optional[str], str]] = (
    set()
)
_turn_counter: Dict[str, int] = {}  # chat_key → turn count


def _memory_identifier(item: Dict[str, Any]) -> Optional[str]:
    """提取统一的记忆ID，便于跨层去重。"""
    for key in ("id", "memory_id"):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _fire_and_forget(coro) -> None:
    """将协程提交到后台执行，不阻塞当前调用。错误仅记录日志。"""

    async def _wrapper():
        try:
            await coro
        except Exception as exc:
            logger.error(f"[Memory] 后台写操作失败: {exc}")

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_wrapper())
    except RuntimeError:
        logger.error("[Memory] 无法提交后台任务：没有运行中的事件循环")


def _build_layer_order(
    scope,
    layers: Optional[List[str]],
    preferred: Optional[str],
    session_enabled: bool,
    agent_enabled: bool,
    bind_persona_to_user: bool,
    prefer_long_term: bool = False,
    guild_enabled: bool = False,
) -> List[str]:
    if layers:
        normalized_layers: List[str] = []
        for layer in layers:
            layer_info = scope.layer_ids(
                layer,
                enable_agent_layer=agent_enabled,
                bind_persona_to_user=bind_persona_to_user,
                enable_guild_layer=guild_enabled,
            )
            if not layer_info:
                continue
            canonical_name = layer_info.get("layer", layer)
            if canonical_name not in normalized_layers:
                normalized_layers.append(canonical_name)
        if normalized_layers:
            return normalized_layers

    default_order = scope.default_layer_order(
        enable_session_layer=session_enabled,
        enable_agent_layer=agent_enabled,
        prefer_long_term=prefer_long_term,
        enable_guild_layer=guild_enabled,
    )

    if preferred:
        normalized_preferred = preferred.strip()
        normalized_lower = normalized_preferred.lower()
        for layer_name in default_order:
            if layer_name.lower() == normalized_lower:
                return [layer_name]

        logger.warning(
            "Invalid preferred memory layer '%s' provided; falling back to default layer order %s",
            preferred,
            default_order,
        )

    return default_order


def _resolve_layer_ids(
    scope: MemoryScope, layer: str, config: Any
) -> Optional[Dict[str, Any]]:
    return scope.layer_ids(
        layer,
        enable_agent_layer=config.ENABLE_AGENT_SCOPE,
        bind_persona_to_user=config.PERSONA_BIND_USER,
        enable_guild_layer=getattr(config, "ENABLE_GUILD_SCOPE", False),
    )


def _resolve_read_layer_ids(
    scope: MemoryScope, layer: str, config: Any
) -> Optional[Dict[str, Any]]:
    resolved = _resolve_layer_ids(scope, layer, config)
    if resolved:
        return resolved

    normalized = (layer or "").strip().lower()
    persona_aliases = {"persona", "preset", "agent"}
    if (
        normalized in persona_aliases
        and getattr(config, "PERSONA_BIND_USER", False)
        and getattr(config, "ENABLE_AGENT_SCOPE", True)
        and scope.agent_id
        and not scope.user_id
    ):
        fallback = scope.layer_ids(
            "persona",
            enable_agent_layer=config.ENABLE_AGENT_SCOPE,
            bind_persona_to_user=False,
            enable_guild_layer=getattr(config, "ENABLE_GUILD_SCOPE", False),
        )
        if fallback:
            logger.info(
                "[Memory] persona 读取回退：当前上下文无 user_id，使用仅 agent_id 兼容读取"
            )
            return fallback

    return None


def _annotate_results(
    raw_results: Any, layer: str, seen_ids: Set[str]
) -> List[Dict[str, Any]]:
    annotated: List[Dict[str, Any]] = []
    for item in normalize_results(raw_results):
        record = dict(item)
        record["layer"] = layer
        memory_id = _memory_identifier(record)
        if memory_id and memory_id in seen_ids:
            continue
        if memory_id:
            seen_ids.add(memory_id)
        annotated.append(record)
    return annotated


def _normalize_cli_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _split_tokens(tokens: List[str]) -> Tuple[List[str], Dict[str, str]]:
    positional: List[str] = []
    kv: Dict[str, str] = {}
    for token in tokens:
        if "=" in token:
            key, val = token.split("=", 1)
            kv[key.strip().lower()] = val.strip()
        else:
            if token:
                positional.append(token)
    return positional, kv


def _parse_layers(layer_value: Optional[str]) -> Optional[List[str]]:
    if not layer_value:
        return None
    normalized = layer_value.strip().lower()
    if normalized in ("*", "all", "any", "默认", "全部"):
        return None
    parts = [
        part.strip() for part in layer_value.replace(",", " ").split() if part.strip()
    ]
    return parts or None


def _parse_tags(tag_value: Optional[str]) -> Optional[List[str]]:
    if not tag_value:
        return None
    if isinstance(tag_value, str):
        parts = [p.strip() for p in tag_value.replace(",", " ").split() if p.strip()]
        return parts or None
    return None


def _parse_metadata(options: Dict[str, str]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    tag = options.get("tag") or options.get("type")
    if tag:
        metadata["TYPE"] = tag
    for key, val in options.items():
        if key.startswith("meta.") or key.startswith("meta_"):
            meta_key = key.split(".", 1)[1] if "." in key else key.split("_", 1)[1]
            if meta_key:
                metadata[meta_key] = val
    return metadata


def _build_scope_from_context(
    context: CommandExecutionContext, options: Dict[str, str]
) -> MemoryScope:
    user_id = _normalize_cli_value(
        options.get("user") or options.get("u") or context.user_id
    )

    # 如果 user_id 是纯数字（旧 OneBot 格式），添加 "private_" 前缀以匹配 db_user.unique_id
    if user_id and user_id.isdigit():
        user_id = f"private_{user_id}"

    agent_id = _normalize_cli_value(
        options.get("agent") or options.get("persona") or options.get("preset")
    )
    run_source = _normalize_cli_value(
        options.get("run")
        or options.get("session")
        or options.get("chat")
        or context.chat_key
    )
    run_id = get_preset_id(run_source) if run_source else None

    logger.debug(
        f"[Memory] 构建作用域 - user_id={user_id}, agent_id={agent_id}, run_id={run_id}, "
        f"run_source={run_source}, context.user_id={context.user_id}, "
        f"context.chat_key={context.chat_key}"
    )

    return MemoryScope(user_id=user_id, agent_id=agent_id, run_id=run_id)


def _build_legacy_value_candidates(layer: str, value: Optional[str]) -> List[str]:
    """构造旧作用域兼容候选值（用于读取回退）。"""
    normalized = _normalize_cli_value(value)
    if not normalized:
        return []

    candidates: List[str] = [normalized]

    if layer == "global":
        if normalized.startswith("private_") and normalized[8:].isdigit():
            candidates.append(normalized[8:])
        elif normalized.isdigit():
            candidates.append(f"private_{normalized}")

    if layer == "persona":
        if normalized.startswith("preset:"):
            raw = normalized.split(":", 1)[1]
            if raw:
                candidates.append(raw)
        else:
            candidates.append(f"preset:{normalized}")

    if layer == "conversation":
        try:
            decoded = decode_id(normalized)
            if decoded:
                candidates.append(decoded)
                candidates.append(get_preset_id(decoded))
        except Exception:
            # 不是有效 base64 时直接忽略
            pass

    deduped: List[str] = []
    for item in candidates:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _build_legacy_layer_variants(layer_ids: Dict[str, Any]) -> List[Dict[str, Any]]:
    """基于当前层级ID构造兼容读取候选层级。"""
    layer = layer_ids.get("layer")
    if layer not in {"global", "persona", "conversation"}:
        return []

    key_by_layer = {
        "global": "user_id",
        "persona": "agent_id",
        "conversation": "run_id",
    }
    key = key_by_layer[layer]
    current_value = layer_ids.get(key)
    candidates = _build_legacy_value_candidates(layer, current_value)

    variants: List[Dict[str, Any]] = []
    for value in candidates:
        variant = {
            "layer": layer,
            "user_id": None,
            "agent_id": None,
            "run_id": None,
        }
        variant[key] = value
        variants.append(variant)

    unique_variants: List[Dict[str, Any]] = []
    seen: Set[Tuple[Optional[str], Optional[str], Optional[str]]] = set()
    for variant in variants:
        fingerprint = (
            variant.get("user_id"),
            variant.get("agent_id"),
            variant.get("run_id"),
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique_variants.append(variant)
    return unique_variants


def _layer_query_kwargs(
    layer_ids: Dict[str, Any], plugin_config: Any
) -> Dict[str, Any]:
    _ = plugin_config
    query_kwargs: Dict[str, Any] = {}
    for key in ("user_id", "agent_id", "run_id"):
        value = layer_ids.get(key)
        if value is not None:
            query_kwargs[key] = value
    return query_kwargs


async def _migrate_records_to_target_layer(
    client: Any,
    raw_results: Any,
    target_layer_ids: Dict[str, Any],
    plugin_config: Any,
) -> None:
    """将兼容读取命中的旧作用域记忆复制到当前目标作用域。"""
    _ = plugin_config
    target_layer = target_layer_ids.get("layer")
    migrated = 0
    seen: Set[str] = set()
    for item in normalize_results(raw_results):
        memory_id = _memory_identifier(item) or ""
        if memory_id and memory_id in seen:
            continue
        if memory_id:
            seen.add(memory_id)

        memory_text = item.get("memory") or item.get("text") or item.get("content")
        if not memory_text:
            continue

        metadata = dict(item.get("metadata") or {})
        metadata.setdefault("_migrated_from_legacy_scope", True)
        if memory_id:
            metadata.setdefault("_source_memory_id", memory_id)

        _add_kw: Dict[str, Any] = {"metadata": metadata, "infer": False}
        if target_layer_ids.get("user_id") is not None:
            _add_kw["user_id"] = target_layer_ids["user_id"]
        if target_layer_ids.get("agent_id") is not None:
            _add_kw["agent_id"] = target_layer_ids["agent_id"]
        if target_layer_ids.get("run_id") is not None:
            _add_kw["run_id"] = target_layer_ids["run_id"]
        await asyncio.to_thread(client.add, memory_text, **_add_kw)
        migrated += 1

    if migrated:
        logger.info(f"[Memory] 自动迁移完成：已复制 {migrated} 条到 {target_layer} 层")


def _schedule_migration_once(
    *,
    client: Any,
    legacy_records: List[Dict[str, Any]],
    target_layer_ids: Dict[str, Any],
    plugin_config: Any,
) -> None:
    migration_key = (
        target_layer_ids.get("user_id"),
        target_layer_ids.get("agent_id"),
        target_layer_ids.get("run_id"),
        str(target_layer_ids.get("layer") or ""),
    )
    if migration_key in _MIGRATION_IN_FLIGHT:
        return
    _MIGRATION_IN_FLIGHT.add(migration_key)

    async def _runner() -> None:
        try:
            await _migrate_records_to_target_layer(
                client=client,
                raw_results=legacy_records,
                target_layer_ids=target_layer_ids,
                plugin_config=plugin_config,
            )
        except Exception as exc:
            logger.error(f"[Memory] 自动迁移失败: {exc}")
        finally:
            _MIGRATION_IN_FLIGHT.discard(migration_key)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_runner())
    except RuntimeError:
        logger.error("[Memory] 无法提交自动迁移任务：没有运行中的事件循环")


async def _read_with_legacy_fallback(
    *,
    client: Any,
    layer_ids: Dict[str, Any],
    plugin_config: Any,
    op: str,
    query: Optional[str] = None,
    limit: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    """读取指定层级，并在启用时回退读取旧作用域格式。"""
    if op not in {"search", "get_all"}:
        raise ValueError(f"unsupported op: {op}")

    def _id_fingerprint(
        ids: Dict[str, Any],
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        return (ids.get("user_id"), ids.get("agent_id"), ids.get("run_id"))

    primary_kwargs = _layer_query_kwargs(layer_ids, plugin_config)
    if op == "search":
        if not query:
            return [], False
        primary_raw = await route_search(
            query=query,
            limit=limit or 5,
            **primary_kwargs,
        )
    else:
        primary_raw = await asyncio.to_thread(client.get_all, **primary_kwargs)

    merged = normalize_results(primary_raw)
    has_primary = bool(merged)
    seen_ids: Set[str] = set()
    for item in merged:
        memory_id = _memory_identifier(item)
        if memory_id:
            seen_ids.add(memory_id)

    legacy_hit = False
    if not getattr(plugin_config, "LEGACY_SCOPE_FALLBACK_ENABLED", True):
        return merged, legacy_hit

    target_fingerprint = _id_fingerprint(layer_ids)
    allow_auto_migrate = getattr(plugin_config, "AUTO_MIGRATE_ON_READ", False)
    if allow_auto_migrate and op == "search" and (not has_primary):
        # search 的空结果不代表目标层无数据（可能只是查询词未命中），避免误迁移。
        existence_probe = await asyncio.to_thread(client.get_all, **primary_kwargs)
        has_primary = bool(normalize_results(existence_probe))

    for variant in _build_legacy_layer_variants(layer_ids):
        if _id_fingerprint(variant) == target_fingerprint:
            continue

        legacy_kwargs = _layer_query_kwargs(variant, plugin_config)
        if op == "search":
            legacy_raw = await route_search(
                query=query,
                limit=limit or 5,
                **legacy_kwargs,
            )
        else:
            legacy_raw = await asyncio.to_thread(client.get_all, **legacy_kwargs)

        legacy_records = normalize_results(legacy_raw)
        if not legacy_records:
            continue

        legacy_hit = True
        for record in legacy_records:
            memory_id = _memory_identifier(record)
            if memory_id and memory_id in seen_ids:
                continue
            if memory_id:
                seen_ids.add(memory_id)
            merged.append(record)

        # 自动迁移采用保守策略：仅当新作用域当前为空时，才把旧作用域结果复制到新作用域
        if allow_auto_migrate and (not has_primary) and legacy_records:
            _schedule_migration_once(
                client=client,
                legacy_records=legacy_records,
                target_layer_ids=layer_ids,
                plugin_config=plugin_config,
            )

    return merged, legacy_hit


def _format_command_error(message: str) -> str:
    return f"❌ {message}"


async def _cleanup_expired_memories() -> None:
    try:
        from datetime import datetime, timezone

        client = await get_mem0_client()
        if client is None:
            return
        now_str = datetime.now(timezone.utc).isoformat()
        logger.info(f"[ExpiryCleanup] 开始清理过期记忆 ({now_str})")
        logger.debug("[ExpiryCleanup] 完成")
    except Exception as exc:
        logger.warning(f"[ExpiryCleanup] 清理失败: {exc}")


async def _start_expiry_cleanup_loop() -> None:
    while True:
        await asyncio.sleep(600)
        await _cleanup_expired_memories()


@plugin.mount_init_method()
async def init_plugin() -> None:
    logger.info("记忆插件初始化中...")
    await get_mem0_client()
    _fire_and_forget(_start_expiry_cleanup_loop())


@plugin.mount_sandbox_method(
    SandboxMethodType.BEHAVIOR,
    name="添加记忆",
    description=(
        "添加记忆（非阻塞）。示例：add_memory('用户喜欢猫', scope_level='global')"
    ),
)
async def add_memory(
    _ctx: Optional[AgentCtx],
    memory: Any,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    scope_level: Optional[str] = None,
    guild_id: Optional[str] = None,
) -> Dict[str, Any]:
    """添加记忆到指定层级（非阻塞，立即返回）。

    scope_level 可选值：conversation / persona / global / guild
    - conversation：仅当前会话有效，用 run_id 隔离
    - persona：绑定人设，跨会话共享，用 agent_id 隔离
    - global：属于用户本人，跨人设跨会话，用 user_id 隔离
    - guild：群组共享记忆，用 guild_id 隔离

    通常只需传 memory 和 scope_level，框架自动从上下文推断 user_id/agent_id/run_id。

    示例：
        await add_memory(_ctx, '喜欢科幻电影', scope_level='persona')
        await add_memory(_ctx, '用户真实姓名：张三', scope_level='global')
    """
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(
        _ctx, user_id=user_id, agent_id=agent_id, run_id=run_id
    )
    if guild_id:
        scope.guild_id = guild_id

    logger.info(
        f"[Memory] 添加记忆 - scope: user_id={scope.user_id}, agent_id={scope.agent_id}, "
        f"run_id={scope.run_id}, guild_id={scope.guild_id}, preset_title={scope.preset_title}, "
        f"参数: user_id={user_id}, agent_id={agent_id}, run_id={run_id}, scope_level={scope_level}"
    )

    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法写入记忆"}

    guild_enabled = getattr(plugin_config, "ENABLE_GUILD_SCOPE", False)
    target_layer = scope.pick_layer(
        preferred=scope_level,
        enable_session_layer=plugin_config.SESSION_ISOLATION,
        enable_agent_layer=plugin_config.ENABLE_AGENT_SCOPE,
        prefer_long_term=True,
        enable_guild_layer=guild_enabled,
    )
    logger.info(
        f"[Memory] 选择层级 - target_layer={target_layer}, SESSION_ISOLATION={plugin_config.SESSION_ISOLATION}, "
        f"ENABLE_AGENT_SCOPE={plugin_config.ENABLE_AGENT_SCOPE}"
    )

    layer_ids = _resolve_layer_ids(scope, target_layer or "", plugin_config)
    if layer_ids is None:
        return {
            "ok": False,
            "error": "未能确定可用的记忆层级，请提供 scope_level 或 user_id/agent_id/run_id",
        }

    # 后台执行实际写入，立即返回不阻塞沙盒
    add_kwargs: Dict[str, Any] = {
        "metadata": metadata or {},
        "infer": False,
    }
    _uid = (
        layer_ids["user_id"]
        if (plugin_config.ENABLE_AGENT_SCOPE or target_layer == "global")
        else None
    )
    _aid = (
        layer_ids["agent_id"]
        if (plugin_config.ENABLE_AGENT_SCOPE or target_layer == "persona")
        else None
    )
    _rid = layer_ids["run_id"]
    if _uid is not None:
        add_kwargs["user_id"] = _uid
    if _aid is not None:
        add_kwargs["agent_id"] = _aid
    if _rid is not None:
        add_kwargs["run_id"] = _rid

    # 去重检查
    if plugin_config.DEDUP_ENABLED:
        hasher = SimHasher()
        new_simhash = hasher.compute_simhash_hex(str(memory))

        search_results = await route_search(
            str(memory), limit=20, user_id=_uid, agent_id=_aid, run_id=_rid
        )
        if search_results:
            for result in search_results:
                result_id = result.get("id") or result.get("memory_id")
                result_text = result.get("memory") or result.get("text", "")

                # 计算 hamming distance
                result_simhash = hasher.compute_simhash_hex(result_text)
                hamming_dist = hamming_distance_hex(new_simhash, result_simhash)

                # 预筛：如果 hamming distance 超过阈值，跳过
                if hamming_dist > plugin_config.DEDUP_SIMHASH_THRESHOLD:
                    continue

                # 计算综合相似度
                similarity = calculate_similarity(str(memory), result_text)

                # 如果相似度超过阈值，返回重复错误
                if similarity >= plugin_config.DEDUP_SIMILARITY_THRESHOLD:
                    return {
                        "ok": False,
                        "error": "记忆重复",
                        "similar_to": result_id,
                        "similarity": similarity,
                    }

    _fire_and_forget(asyncio.to_thread(client.add, memory, **add_kwargs))
    return {"ok": True, "layer": layer_ids["layer"], "message": "记忆已提交写入"}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="搜索记忆",
    description=(
        "语义搜索记忆（阻塞，等待结果）。"
        "示例：search_memory('查询词', layers=['global'])"
    ),
)
async def search_memory(
    _ctx: Optional[AgentCtx],
    query: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    scope_level: Optional[str] = None,
    layers: Optional[List[str]] = None,
    limit: int = 5,
    guild_id: Optional[str] = None,
) -> Dict[str, Any]:
    """通过语义检索搜索记忆（阻塞直到返回结果）。

    仅用于具体语义查询（如"我喜欢什么""之前说过XX吗"）。
    不要用于全量枚举（应使用 get_all_memory）。

    示例：
        result = await search_memory(_ctx, '和主人的记忆', layers=['persona', 'global'], limit=20)
    """
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    if should_skip_retrieval(query):
        return {"ok": True, "results": [], "text": "(查询被跳过：无需检索)"}

    scope = resolve_memory_scope(
        _ctx, user_id=user_id, agent_id=agent_id, run_id=run_id
    )
    if guild_id:
        scope.guild_id = guild_id
    if not scope.has_scope():
        return {
            "ok": False,
            "error": "缺少可用的 user_id/agent_id/run_id，无法搜索记忆",
        }

    guild_enabled = getattr(plugin_config, "ENABLE_GUILD_SCOPE", False)
    layer_order = _build_layer_order(
        scope,
        layers=layers,
        preferred=scope_level,
        session_enabled=plugin_config.SESSION_ISOLATION,
        agent_enabled=plugin_config.ENABLE_AGENT_SCOPE,
        bind_persona_to_user=plugin_config.PERSONA_BIND_USER,
        guild_enabled=guild_enabled,
    )
    if not layer_order:
        return {"ok": False, "error": "未找到可搜索的层级"}

    merged_results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for layer in layer_order:
        layer_ids = _resolve_read_layer_ids(scope, layer, plugin_config)
        if not layer_ids:
            continue
        raw_results, legacy_hit = await _read_with_legacy_fallback(
            client=client,
            layer_ids=layer_ids,
            plugin_config=plugin_config,
            op="search",
            query=query,
            limit=limit,
        )
        if legacy_hit:
            logger.info(f"[Memory] 层级 {layer} 触发旧作用域兼容读取")
        merged_results.extend(
            _annotate_results(raw_results, layer_ids["layer"], seen_ids)
        )

    merged_results.sort(
        key=lambda item: _get_combined_score(
            item, importance_weight=plugin_config.IMPORTANCE_WEIGHT
        ),
        reverse=True,
    )
    merged_results = merged_results[:limit]

    formatted = format_search_output(
        merged_results,
        threshold=plugin_config.MEMORY_SEARCH_SCORE_THRESHOLD,
        importance_weight=plugin_config.IMPORTANCE_WEIGHT,
    )
    return {"ok": True, **formatted}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="获取记忆列表",
    description=(
        "列出全部记忆（阻塞，等待结果）。"
        "示例：get_all_memory(layers=['global'], tags=['FACTS'])"
    ),
)
async def get_all_memory(
    _ctx: Optional[AgentCtx],
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    scope_level: Optional[str] = None,
    layers: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    列出全部记忆（阻塞，等待结果）。

    layers 可选值：['conversation', 'persona', 'global']
    tags 可选值：['FACTS', 'PREFERENCES', 'GOALS', 'TRAITS', 'RELATIONSHIPS', 'EVENTS', 'TOPICS']

    示例：
        get_all_memory(layers=['persona'])
        get_all_memory(layers=['persona', 'global'], tags=['PREFERENCES'])
    """
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(
        _ctx, user_id=user_id, agent_id=agent_id, run_id=run_id
    )
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法获取记忆"}

    layer_order = _build_layer_order(
        scope,
        layers=layers,
        preferred=scope_level,
        session_enabled=plugin_config.SESSION_ISOLATION,
        agent_enabled=plugin_config.ENABLE_AGENT_SCOPE,
        bind_persona_to_user=plugin_config.PERSONA_BIND_USER,
    )
    if not layer_order:
        return {"ok": False, "error": "未找到可获取的层级"}

    merged_results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for layer in layer_order:
        layer_ids = _resolve_read_layer_ids(scope, layer, plugin_config)
        if not layer_ids:
            continue
        raw, legacy_hit = await _read_with_legacy_fallback(
            client=client,
            layer_ids=layer_ids,
            plugin_config=plugin_config,
            op="get_all",
        )
        if legacy_hit:
            logger.info(f"[Memory] 层级 {layer} 触发旧作用域兼容读取")
        merged_results.extend(_annotate_results(raw, layer_ids["layer"], seen_ids))

    formatted = format_get_all_output(merged_results, tags=tags)
    return {"ok": True, **formatted}


@plugin.mount_sandbox_method(
    SandboxMethodType.BEHAVIOR,
    name="更新记忆",
    description=("更新记忆内容（非阻塞）。示例：update_memory(memory_id, '新内容')"),
)
async def update_memory(
    _ctx: Optional[AgentCtx],
    memory_id: str,
    new_memory: str,
) -> Dict[str, Any]:
    """
    更新记忆内容（非阻塞，立即返回）。

    memory_id 全局唯一，无需指定层级。

    示例：
        update_memory(memory_id="abc123", new_memory="改为喜欢爵士乐")
    """
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    # 后台执行实际更新，立即返回不阻塞沙盒
    _fire_and_forget(asyncio.to_thread(client.update, memory_id, new_memory))
    return {"ok": True, "message": "记忆更新已提交"}


@plugin.mount_sandbox_method(
    SandboxMethodType.BEHAVIOR,
    name="删除记忆",
    description=(
        "删除单条记忆（非阻塞）。主动清理过时/矛盾的记忆。"
        "示例：delete_memory(memory_id)"
    ),
)
async def delete_memory(
    _ctx: Optional[AgentCtx],
    memory_id: str,
) -> Dict[str, Any]:
    """
    删除单条记忆（非阻塞，立即返回）。

    主动清理过时记忆的场景：
    - 用户更正信息（"我其实不喜欢XX" → 删除旧记忆）
    - 偏好变化（换工作、搬家 → 删除旧地址/工作）
    - 信息矛盾（保留最新，删除过时）

    示例：
        delete_memory(memory_id="abc123")
    """
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    # 后台执行实际删除，立即返回不阻塞沙盒
    _fire_and_forget(asyncio.to_thread(client.delete, memory_id))
    return {"ok": True, "message": "记忆删除已提交"}


@plugin.mount_sandbox_method(
    SandboxMethodType.BEHAVIOR,
    name="删除作用域记忆",
    description=(
        "批量删除记忆（非阻塞，危险操作）。示例：delete_all_memory(layers=['global'])"
    ),
)
async def delete_all_memory(
    _ctx: Optional[AgentCtx],
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    scope_level: Optional[str] = None,
    layers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    批量删除记忆（非阻塞，危险操作）。

    示例：
        delete_all_memory(layers=['persona'])
        delete_all_memory(layers=['persona', 'global'])
    """
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(
        _ctx, user_id=user_id, agent_id=agent_id, run_id=run_id
    )
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法删除记忆"}

    layer_order = _build_layer_order(
        scope,
        layers=layers,
        preferred=scope_level,
        session_enabled=plugin_config.SESSION_ISOLATION,
        agent_enabled=plugin_config.ENABLE_AGENT_SCOPE,
        bind_persona_to_user=plugin_config.PERSONA_BIND_USER,
    )
    if not layer_order:
        return {"ok": False, "error": "未找到可删除的层级"}

    # 收集需要删除的层级信息，提交到后台执行
    target_layers: List[str] = []
    for layer in layer_order:
        layer_ids = _resolve_layer_ids(scope, layer, plugin_config)
        if not layer_ids:
            continue
        target_layers.append(layer_ids["layer"])

        async def _do_delete_all(_layer_ids=layer_ids):
            _del_kw: Dict[str, Any] = {}
            if _layer_ids.get("user_id") is not None:
                _del_kw["user_id"] = _layer_ids["user_id"]
            if _layer_ids.get("agent_id") is not None:
                _del_kw["agent_id"] = _layer_ids["agent_id"]
            if _layer_ids.get("run_id") is not None:
                _del_kw["run_id"] = _layer_ids["run_id"]
            await asyncio.to_thread(client.delete_all, **_del_kw)

        _fire_and_forget(_do_delete_all())

    if not target_layers:
        return {"ok": False, "error": "未能匹配任何可删除的层级"}
    return {"ok": True, "message": f"已提交删除作用域记忆：{', '.join(target_layers)}"}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="获取记忆历史",
    description=(
        "查看记忆历史版本（阻塞，等待结果）。示例：get_memory_history(memory_id)"
    ),
)
async def get_memory_history(
    _ctx: Optional[AgentCtx],
    memory_id: str,
) -> Dict[str, Any]:
    """
    查看记忆历史版本（阻塞，等待结果）。

    示例：
        get_memory_history(memory_id="abc123")
    """
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    try:
        results = await asyncio.to_thread(client.history, memory_id)
    except Exception as exc:  # pragma: no cover
        logger.error(f"获取记忆历史失败: {exc}")
        return {"ok": False, "error": str(exc)}

    history_list = format_history_output(results)
    return {
        "ok": True,
        "results": history_list,
        "text": format_history_text(history_list),
    }


@plugin.mount_sandbox_method(
    SandboxMethodType.BEHAVIOR,
    name="记忆指令面板",
    description=(
        "统一命令入口（支持 add/search/list/update/delete/delete_all/history）。"
        "示例：memory_command('search', {'query': '查询词'})"
    ),
)
async def memory_command(
    _ctx: Optional[AgentCtx],
    action: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    统一命令入口（支持 add/search/list/update/delete/delete_all/history）。

    示例：
        memory_command('search', {'query': '最喜欢的颜色', 'layers': ['global']})
    """
    if isinstance(payload, str):
        import json as _json

        try:
            payload = _json.loads(payload)
        except (ValueError, TypeError):
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    action = (action or "").lower()

    if action == "add":
        return await add_memory(
            _ctx,
            memory=payload.get("memory"),
            user_id=payload.get("user_id"),
            metadata=payload.get("metadata"),
            agent_id=payload.get("agent_id"),
            run_id=payload.get("run_id"),
            scope_level=payload.get("scope_level"),
        )
    if action == "search":
        resp = await search_memory(
            _ctx,
            query=payload.get("query", ""),
            user_id=payload.get("user_id"),
            agent_id=payload.get("agent_id"),
            run_id=payload.get("run_id"),
            scope_level=payload.get("scope_level"),
            layers=payload.get("layers"),
            limit=payload.get("limit", 5),
        )
        if resp.get("ok"):
            resp["text"] = resp.get("text") or _format_memory_list(
                resp.get("results", [])
            )
        return resp
    if action == "list":
        resp = await get_all_memory(
            _ctx,
            user_id=payload.get("user_id"),
            agent_id=payload.get("agent_id"),
            run_id=payload.get("run_id"),
            scope_level=payload.get("scope_level"),
            layers=payload.get("layers"),
            tags=payload.get("tags"),
        )
        return resp
    if action == "update":
        return await update_memory(
            _ctx,
            memory_id=payload.get("memory_id", ""),
            new_memory=payload.get("new_memory", ""),
        )
    if action == "delete":
        return await delete_memory(_ctx, memory_id=payload.get("memory_id", ""))
    if action == "delete_all":
        return await delete_all_memory(
            _ctx,
            user_id=payload.get("user_id"),
            agent_id=payload.get("agent_id"),
            run_id=payload.get("run_id"),
            scope_level=payload.get("scope_level"),
            layers=payload.get("layers"),
        )
    if action == "history":
        return await get_memory_history(_ctx, memory_id=payload.get("memory_id", ""))

    return {"ok": False, "error": f"未知操作: {action}"}


async def _search_single_layer(
    client: Any, query: str, layer_ids: Dict[str, Any], limit: int, config: Any
) -> Tuple[str, Any]:
    """
    搜索单个记忆层级。

    Args:
        client: mem0 客户端
        query: 搜索查询
        layer_ids: 层级标识符（包含 layer, user_id, agent_id, run_id）
        limit: 结果数量限制
        config: 插件配置

    Returns:
        (layer_name, search_results) 元组
    """
    layer = layer_ids["layer"]

    # 执行搜索（含旧作用域兼容回退）
    try:
        results, legacy_hit = await _read_with_legacy_fallback(
            client=client,
            layer_ids=layer_ids,
            plugin_config=config,
            op="search",
            query=query,
            limit=limit,
        )
        if legacy_hit:
            logger.info(f"[PreSearch] 层级 {layer} 触发旧作用域兼容读取")
        return (layer, results)
    except Exception as exc:
        logger.warning(f"[Memory] 层级 {layer} 搜索失败: {exc}")
        return (layer, None)


async def _ensure_pre_search_results(
    merged_results: List[Dict[str, Any]],
    seen_ids: Set[str],
    layer_order: List[str],
    scope: MemoryScope,
    config: Any,
    client: Any,
    query: str,
) -> List[Dict[str, Any]]:
    if merged_results:
        return merged_results

    conversation_in_order = any(layer == "conversation" for layer in layer_order)
    if not config.PRE_SEARCH_SKIP_CONVERSATION or conversation_in_order:
        return merged_results

    conversation_layer_ids = _resolve_read_layer_ids(scope, "conversation", config)
    if not conversation_layer_ids:
        return merged_results

    conversation_layer, conversation_raw_results = await _search_single_layer(
        client,
        query,
        conversation_layer_ids,
        config.PRE_SEARCH_RESULT_LIMIT,
        config,
    )
    if conversation_raw_results is None:
        return merged_results

    conversation_annotated = _annotate_results(
        conversation_raw_results, conversation_layer, seen_ids
    )
    merged_results.extend(conversation_annotated)
    if conversation_annotated:
        logger.info("[PreSearch] 首轮无结果，conversation 层兜底命中")
    return merged_results


def _select_pre_search_injection_text(
    top_results: List[Dict[str, Any]], threshold: Optional[float]
) -> Tuple[Optional[str], List[Dict[str, Any]], bool]:
    formatted = format_search_output(top_results, threshold=threshold)
    result_text = formatted.get("text", "")
    injected_results = formatted.get("results") or []
    if result_text and result_text != "(无结果)":
        return result_text, injected_results, False

    fallback_formatted = format_search_output(top_results, threshold=None)
    fallback_text = fallback_formatted.get("text", "")
    fallback_results = fallback_formatted.get("results") or []
    if fallback_text and fallback_text != "(无结果)":
        return fallback_text, fallback_results, True

    return None, [], False


def _pre_search_skip(reason_code: str, message: str) -> None:
    logger.info(f"[PreSearch] 未注入原因({reason_code}): {message}")


async def _fetch_recent_messages(
    _ctx: AgentCtx, message_count: int
) -> List[Dict[str, Any]]:
    """
    从数据库获取最近的历史消息。

    Args:
        _ctx: Agent 上下文
        message_count: 要获取的消息数量

    Returns:
        消息列表，格式 [{'role': 'user', 'content': '...'}]
    """
    try:
        chat_key = getattr(_ctx, "chat_key", None)
        if not chat_key:
            logger.debug("[PreSearch] 无 chat_key，跳过消息获取")
            return []

        # 从数据库获取消息（按时间倒序）
        db_messages = (
            await DBChatMessage.filter(chat_key=chat_key)
            .order_by("-send_timestamp")
            .limit(message_count)
        )

        if not db_messages:
            logger.debug("[PreSearch] 未找到历史消息")
            return []

        # 转换为标准格式（时间正序）
        messages = convert_db_messages_to_dict(db_messages)
        messages.reverse()  # 倒序变正序（最早的在前）

        logger.debug(f"[PreSearch] 获取到 {len(messages)} 条历史消息")
        return messages

    except Exception as exc:
        logger.warning(f"[PreSearch] 获取历史消息失败: {exc}")
        return []


async def _execute_pre_search(_ctx: AgentCtx) -> Optional[str]:
    """
    执行预搜索：获取历史消息 → 生成查询 → 并行搜索 → 格式化结果。

    Args:
        _ctx: Agent 上下文

    Returns:
        格式化的预搜索结果字符串，失败则返回 None
    """
    config = get_memory_config()
    try:
        # 1. 获取历史消息
        messages = await _fetch_recent_messages(
            _ctx, config.PRE_SEARCH_DB_MESSAGE_COUNT
        )

        if not messages:
            logger.debug("[PreSearch] 无历史消息，跳过预搜索")
            _pre_search_skip("NO_MESSAGES", "未获取到历史消息")
            return None

        # 2. 生成查询
        query = build_pre_search_query(
            messages,
            config.PRE_SEARCH_QUERY_MESSAGE_COUNT,
            config.PRE_SEARCH_QUERY_MAX_LENGTH,
        )

        if not query:
            logger.debug("[PreSearch] 无法生成查询，跳过预搜索")
            _pre_search_skip("NO_QUERY", "无法从历史消息生成查询")
            return None

        logger.info(f"[PreSearch] 生成查询: {query[:100]}...")

        # 查询改写（可选）
        if config.QUERY_REWRITE_ENABLED:
            try:
                from .query_rewrite import rewrite_query
                from .utils import get_model_group_info
                import httpx

                llm_group = get_model_group_info(
                    config.MEMORY_MANAGE_MODEL, expected_type="chat"
                )

                async def _llm_invoke(prompt_text: str) -> str:
                    async with httpx.AsyncClient(timeout=15.0) as http_client:
                        resp = await http_client.post(
                            f"{llm_group.BASE_URL}/chat/completions",
                            headers={"Authorization": f"Bearer {llm_group.API_KEY}"},
                            json={
                                "model": llm_group.CHAT_MODEL,
                                "messages": [{"role": "user", "content": prompt_text}],
                                "temperature": 0.1,
                            },
                        )
                        resp.raise_for_status()
                        return resp.json()["choices"][0]["message"]["content"]

                rewritten = await rewrite_query(_llm_invoke, messages, query)
                if rewritten:
                    if should_skip_retrieval(rewritten):
                        logger.info("[PreSearch] 查询改写返回 [skip]，跳过预搜索")
                        return None
                    logger.info(f"[PreSearch] 查询已改写: {rewritten[:100]}...")
                    query = rewritten
            except Exception as exc:
                logger.warning(f"[PreSearch] 查询改写失败，使用原始查询: {exc}")

        # 3. 解析作用域
        scope = resolve_memory_scope(_ctx)
        if not scope.has_scope():
            logger.debug("[PreSearch] 无有效作用域，跳过预搜索")
            _pre_search_skip("NO_SCOPE", "user_id/agent_id/run_id 全为空")
            return None

        # 4. 确定搜索层级
        layer_order = scope.default_layer_order(
            enable_session_layer=config.SESSION_ISOLATION,
            enable_agent_layer=config.ENABLE_AGENT_SCOPE,
        )

        # 如果配置跳过 conversation 层，则过滤掉
        if config.PRE_SEARCH_SKIP_CONVERSATION:
            filtered_layer_order = [
                layer for layer in layer_order if layer != "conversation"
            ]
            if filtered_layer_order:
                layer_order = filtered_layer_order
            else:
                logger.debug(
                    "[PreSearch] 跳过 conversation 后无可用层级，回退为仅 conversation 层"
                )

        if not layer_order:
            logger.debug("[PreSearch] 无可搜索层级，跳过预搜索")
            _pre_search_skip("NO_LAYER_ORDER", "未解析到可搜索层级")
            return None

        logger.debug(f"[PreSearch] 搜索层级: {layer_order}")

        # 5. 获取 mem0 客户端
        client = await get_mem0_client()
        if client is None:
            logger.warning("[PreSearch] mem0 客户端初始化失败")
            _pre_search_skip("NO_CLIENT", "mem0 客户端初始化失败")
            return None

        # 6. 并行搜索所有层级
        search_tasks = []

        for layer in layer_order:
            layer_ids = _resolve_read_layer_ids(scope, layer, config)
            if not layer_ids:
                continue

            search_tasks.append(
                asyncio.create_task(
                    _search_single_layer(
                        client,
                        query,
                        layer_ids,
                        config.PRE_SEARCH_RESULT_LIMIT,
                        config,
                    )
                )
            )

        if not search_tasks:
            logger.debug("[PreSearch] 无有效层级，跳过预搜索")
            _pre_search_skip("NO_SEARCH_TASKS", "层级存在但均无法构建检索任务")
            return None

        # 并行执行（带总超时）：超时后保留已完成结果，取消未完成任务
        done, pending = await asyncio.wait(
            search_tasks,
            timeout=config.PRE_SEARCH_TIMEOUT,
            return_when=asyncio.ALL_COMPLETED,
        )

        if pending:
            logger.warning(
                f"[PreSearch] 部分超时：{len(pending)}/{len(search_tasks)} 个层级超时，使用已完成结果继续"
            )
            for pending_task in pending:
                pending_task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        layer_results: List[Tuple[str, Any]] = []
        for done_task in done:
            if done_task.cancelled():
                continue
            result = done_task.result()
            layer_results.append(result)

        if not layer_results:
            logger.warning(
                f"[PreSearch] 所有层级均超时（>{config.PRE_SEARCH_TIMEOUT}s），降级"
            )
            _pre_search_skip("ALL_TIMEOUT", "所有层级超时")
            return None

        # 7. 合并结果并去重
        merged_results: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()

        for layer_name, raw_results in layer_results:
            if raw_results is None:
                continue

            annotated = _annotate_results(raw_results, layer_name, seen_ids)
            merged_results.extend(annotated)

        merged_results = await _ensure_pre_search_results(
            merged_results,
            seen_ids,
            layer_order,
            scope,
            config,
            client,
            query,
        )

        if not merged_results:
            logger.debug("[PreSearch] 无搜索结果")
            _pre_search_skip("NO_RESULTS", "首轮与兜底均无搜索结果")
            return None

        # 8. 按分数排序并限制数量
        merged_results.sort(
            key=lambda item: _get_combined_score(
                item, importance_weight=config.IMPORTANCE_WEIGHT
            ),
            reverse=True,
        )
        completed_layer_count = max(1, len(layer_results))
        top_results = merged_results[
            : config.PRE_SEARCH_RESULT_LIMIT * completed_layer_count
        ]

        pre_search_threshold = config.PRE_SEARCH_SCORE_THRESHOLD
        if pre_search_threshold is None:
            pre_search_threshold = config.MEMORY_SEARCH_SCORE_THRESHOLD

        result_text, injected_results, threshold_fallback_hit = (
            _select_pre_search_injection_text(
                top_results, threshold=pre_search_threshold
            )
        )
        if threshold_fallback_hit:
            logger.info("[PreSearch] 阈值过滤后为空，回退为低阈值结果注入")
        if not result_text:
            logger.debug("[PreSearch] 阈值过滤后无可注入结果，跳过预搜索")
            _pre_search_skip("NO_INJECTABLE_TEXT", "结果存在但不可格式化为可注入文本")
            return None

        logger.info(f"[PreSearch] 成功检索到 {len(injected_results)} 条记忆")
        return result_text

    except asyncio.TimeoutError:
        logger.warning(f"[PreSearch] 超时（>{config.PRE_SEARCH_TIMEOUT}s），降级")
        _pre_search_skip("TIMEOUT_EXCEPTION", "预搜索整体超时异常")
        return None
    except Exception as exc:
        logger.warning(f"[PreSearch] 执行失败: {exc}", exc_info=True)
        _pre_search_skip("EXECUTION_EXCEPTION", f"执行异常: {exc}")
        return None


async def _do_passive_extraction(
    _ctx: AgentCtx,
    conversation_text: str,
    config: Any,
) -> None:
    try:
        from .utils import get_model_group_info
        import httpx

        llm_group = get_model_group_info(
            config.MEMORY_MANAGE_MODEL, expected_type="chat"
        )

        prompt = ENHANCED_MEMORY_PROMPT.format(conversation=conversation_text)

        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.post(
                f"{llm_group.BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {llm_group.API_KEY}"},
                json={
                    "model": llm_group.CHAT_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()
            result_text = response.json()["choices"][0]["message"]["content"]

        memories = parse_extracted_memories(result_text)
        if not memories:
            logger.debug("[AutoExtract] 未提取到记忆")
            return

        logger.info(f"[AutoExtract] 提取到 {len(memories)} 条记忆")

        for mem in memories:
            await add_memory(
                _ctx,
                memory=mem["content"],
                metadata={
                    "TYPE": mem.get("type", "contextual"),
                    "importance": mem.get("importance", 5),
                    "_auto_extracted": True,
                },
                scope_level=config.AUTO_EXTRACT_TARGET_LAYER,
            )
    except Exception as exc:
        logger.error(f"[AutoExtract] 提取执行失败: {exc}")


@plugin.mount_prompt_inject_method(
    name="memory_layer_hint",
    description="为LLM注入可用的长期记忆能力提示，包含跨用户/Agent/会话的存取方式",
)
async def inject_memory_prompt(_ctx: AgentCtx) -> str:
    config = get_memory_config()

    # 执行预搜索（优雅降级：任何失败都不影响基础提示）
    pre_search_section = ""
    if config.PRE_SEARCH_ENABLED:
        try:
            pre_search_results = await _execute_pre_search(_ctx)
            if pre_search_results:
                pre_search_section = (
                    "\n\n📚 【预加载记忆】（基于最近对话自动检索）：\n"
                    + pre_search_results
                    + "\n"
                )
                logger.info("[PreSearch] 预搜索结果已注入提示")
            else:
                logger.info("[PreSearch] 本次未注入：未检索到可注入结果")
        except Exception as exc:
            # 优雅降级：任何异常都不影响基础提示
            logger.warning(f"[PreSearch] 预搜索失败，降级到基础提示: {exc}")
    else:
        logger.info("[PreSearch] 已禁用：PRE_SEARCH_ENABLED=False")

    if config.AUTO_EXTRACT_ENABLED:
        try:
            chat_key = getattr(_ctx, "chat_key", None) or ""
            _turn_counter[chat_key] = _turn_counter.get(chat_key, 0) + 1
            current_turn = _turn_counter[chat_key]

            if current_turn % config.AUTO_EXTRACT_INTERVAL == 0:
                logger.info(f"[AutoExtract] 触发被动提取 (turn={current_turn})")
                extract_messages = await _fetch_recent_messages(
                    _ctx, config.AUTO_EXTRACT_INTERVAL * 2
                )
                if extract_messages:
                    conversation_text = "\n".join(
                        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                        for m in extract_messages
                        if m.get("content", "").strip()
                    )

                    if conversation_text.strip():
                        _fire_and_forget(
                            _do_passive_extraction(_ctx, conversation_text, config)
                        )
        except Exception as exc:
            logger.warning(f"[AutoExtract] 被动提取失败: {exc}")

    scope = resolve_memory_scope(_ctx)
    layer_order = scope.default_layer_order(
        enable_session_layer=config.SESSION_ISOLATION,
        enable_agent_layer=config.ENABLE_AGENT_SCOPE,
    )
    available_layers = ", ".join(layer_order) if layer_order else "无可用层级"
    lines = [
        "# 长期记忆插件",
        f"可用层级: {available_layers} | 阈值: {config.MEMORY_SEARCH_SCORE_THRESHOLD}",
        "",
        "## ⚠️ 调用规则（必读）",
        "所有记忆函数的第一个参数 _ctx 由框架自动注入，调用时必须省略！",
        "❌ 错误：add_memory(_ctx, '内容')  # 会导致 NameError",
        "✅ 正确：add_memory('内容', scope_level='global')",
        "",
        "## 写操作（非阻塞，可与 send_text 同一代码块）",
        "await add_memory(‘用户喜欢猫’, scope_level=’global’)",
        "await add_memory(‘用户今天心情好’, scope_level=’persona’)",
        "await send_text(_ctx, ‘好的，我记住了！’)  # send_text 仍需 _ctx",
        "",
        "## 读操作（必须单独代码块，等待结果后再 send_text）",
        "result = await search_memory(‘用户喜欢什么’)  # 语义搜索",
        "result = await search_memory(‘猫’, layers=[‘global’])  # 指定层",
        "result = await get_all_memory()  # 列出全部（不要用 search_memory 代替）",
        "result = await get_all_memory(layers=[‘global’])  # 指定层全部",
        "",
        "## 维护",
        "await update_memory(memory_id, ‘新内容’)  # 更新",
        "await delete_memory(memory_id)  # 删除过时记忆（主动维护！）",
        "",
        "## 层级说明",
        "conversation: 仅当前对话有效",
        "persona: 绑定当前人设，跨会话共享",
        "global: 属于用户本人，跨人设跨会话",
        "",
        "## 记忆维护原则",
        "用户更正信息时：先 search_memory 找旧记忆 → delete_memory → add_memory 写新的",
    ]

    if config.ENABLE_AGENT_SCOPE:
        lines.append(
            "已启用 Agent/人设 级记忆：同一人设可在多会话间共享知识，不同人设彼此隔离。"
        )
        if config.PERSONA_BIND_USER:
            lines.append(
                "persona 层已启用用户绑定：同一 agent_id 在不同用户之间不会共享记忆。"
            )
    else:
        lines.append("未启用 Agent 级记忆：记忆主要按用户/会话维度隔离。")

    if config.SESSION_ISOLATION:
        lines.append(
            "已启用会话隔离：检索时优先限定 run_id（会话层），确保结果贴合当前对话。"
        )
    else:
        lines.append("已关闭会话隔离：检索会聚合用户/Agent 级记忆，便于跨会话互通。")

    if scope.run_id:
        lines.append(f"对话层 run_id: {scope.run_id}")
    if scope.persona_id:
        lines.append(f"人设层 agent_id: {scope.persona_id}")
    if scope.user_id:
        lines.append(f"全局层 user_id: {scope.user_id}")

    # 将预搜索结果注入到提示开头
    base_prompt = "\n".join(lines)
    return pre_search_section + base_prompt


# ============ 聊天指令：/mem ===============


async def _command_list_memory(
    scope: MemoryScope, layers: Optional[List[str]], tags: Optional[List[str]]
) -> str:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return _format_command_error("mem0 client init failed，检查插件配置。")

    logger.info(
        f"[Memory] 列出记忆 - user_id={scope.user_id}, agent_id={scope.agent_id}, "
        f"run_id={scope.run_id}, has_scope={scope.has_scope()}, layers={layers}"
    )

    if not scope.has_scope():
        return _format_command_error("缺少 user_id/agent_id/run_id，无法列出记忆。")

    layer_order = _build_layer_order(
        scope,
        layers=layers,
        preferred=None,
        session_enabled=plugin_config.SESSION_ISOLATION,
        agent_enabled=plugin_config.ENABLE_AGENT_SCOPE,
        bind_persona_to_user=plugin_config.PERSONA_BIND_USER,
    )
    logger.info(
        f"[Memory] 层级顺序: {layer_order}, SESSION_ISOLATION={plugin_config.SESSION_ISOLATION}"
    )

    if not layer_order:
        return _format_command_error("未找到可获取的层级。")

    merged_results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for layer in layer_order:
        layer_ids = _resolve_layer_ids(scope, layer, plugin_config)
        if not layer_ids:
            logger.warning(f"[Memory] 跳过层级 {layer}，layer_ids 为空")
            continue

        query_user_id = layer_ids["user_id"]
        query_agent_id = layer_ids["agent_id"]
        query_run_id = layer_ids["run_id"]

        logger.info(
            f"[Memory] 查询层级 {layer} - user_id={query_user_id}, "
            f"agent_id={query_agent_id}, run_id={query_run_id}, "
            f"ENABLE_AGENT_SCOPE={plugin_config.ENABLE_AGENT_SCOPE}"
        )

        raw, legacy_hit = await _read_with_legacy_fallback(
            client=client,
            layer_ids=layer_ids,
            plugin_config=plugin_config,
            op="get_all",
        )
        if legacy_hit:
            logger.info(f"[Memory] 层级 {layer} 触发旧作用域兼容读取")
        logger.info(f"[Memory] 层级 {layer} 返回 {len(raw) if raw else 0} 条记忆")
        merged_results.extend(_annotate_results(raw, layer_ids["layer"], seen_ids))

    formatted = format_get_all_output(merged_results, tags=tags)
    logger.info(f"[Memory] 合并后共 {len(merged_results)} 条记忆")
    return "📒 记忆列表：\n" + (formatted.get("text") or "(无结果)")


async def _command_delete_memory(memory_id: str) -> str:
    client = await get_mem0_client()
    if client is None:
        return _format_command_error("mem0 client init failed，检查插件配置。")
    try:
        await asyncio.to_thread(client.delete, memory_id)
    except Exception as exc:  # pragma: no cover
        logger.error(f"删除记忆失败: {exc}")
        return _format_command_error(str(exc))
    return f"🗑️ 已删除记忆 {memory_id}"


async def _command_clear_memory(scope: MemoryScope, layers: Optional[List[str]]) -> str:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return _format_command_error("mem0 client init failed，检查插件配置。")
    if not scope.has_scope():
        return _format_command_error("缺少 user_id/agent_id/run_id，无法清空记忆。")

    layer_order = _build_layer_order(
        scope,
        layers=layers,
        preferred=None,
        session_enabled=plugin_config.SESSION_ISOLATION,
        agent_enabled=plugin_config.ENABLE_AGENT_SCOPE,
        bind_persona_to_user=plugin_config.PERSONA_BIND_USER,
    )
    if not layer_order:
        return _format_command_error("未找到可删除的层级。")

    deleted_layers: List[str] = []
    try:
        for layer in layer_order:
            layer_ids = _resolve_layer_ids(scope, layer, plugin_config)
            if not layer_ids:
                continue
            _del_kw: Dict[str, Any] = {}
            if layer_ids.get("user_id") is not None:
                _del_kw["user_id"] = layer_ids["user_id"]
            if layer_ids.get("agent_id") is not None:
                _del_kw["agent_id"] = layer_ids["agent_id"]
            if layer_ids.get("run_id") is not None:
                _del_kw["run_id"] = layer_ids["run_id"]
            await asyncio.to_thread(client.delete_all, **_del_kw)
            deleted_layers.append(layer_ids["layer"])
    except Exception as exc:  # pragma: no cover
        logger.error(f"清空记忆失败: {exc}")
        return _format_command_error(str(exc))

    if not deleted_layers:
        return _format_command_error("未能匹配任何可删除的层级。")
    return f"🧹 已删除层级：{', '.join(deleted_layers)}"


async def _command_history(memory_id: str) -> str:
    client = await get_mem0_client()
    if client is None:
        return _format_command_error("mem0 client init failed，检查插件配置。")
    try:
        results = await asyncio.to_thread(client.history, memory_id)
    except Exception as exc:  # pragma: no cover
        logger.error(f"获取历史失败: {exc}")
        return _format_command_error(str(exc))
    history_list = format_history_output(results)
    text = format_history_text(history_list)
    return "📜 记忆历史：\n" + text


async def _command_search(
    scope: MemoryScope, query: str, layers: Optional[List[str]], limit: int
) -> str:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return _format_command_error("mem0 client init failed，检查插件配置。")

    logger.info(
        f"[Memory] 搜索记忆 - query='{query}', user_id={scope.user_id}, agent_id={scope.agent_id}, "
        f"run_id={scope.run_id}, has_scope={scope.has_scope()}, layers={layers}, limit={limit}"
    )

    if not scope.has_scope():
        return _format_command_error("缺少 user_id/agent_id/run_id，无法搜索记忆。")
    layer_order = _build_layer_order(
        scope,
        layers=layers,
        preferred=None,
        session_enabled=plugin_config.SESSION_ISOLATION,
        agent_enabled=plugin_config.ENABLE_AGENT_SCOPE,
        bind_persona_to_user=plugin_config.PERSONA_BIND_USER,
    )
    logger.info(
        f"[Memory] 搜索层级顺序: {layer_order}, SESSION_ISOLATION={plugin_config.SESSION_ISOLATION}"
    )

    if not layer_order:
        return _format_command_error("未找到可搜索的层级。")

    merged_results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for layer in layer_order:
        layer_ids = _resolve_layer_ids(scope, layer, plugin_config)
        if not layer_ids:
            logger.warning(f"[Memory] 搜索跳过层级 {layer}，layer_ids 为空")
            continue
        search_run_id = layer_ids["run_id"]
        search_agent_id = layer_ids["agent_id"]
        search_user_id = layer_ids["user_id"]

        logger.info(
            f"[Memory] 在层级 {layer} 搜索 - user_id={search_user_id}, "
            f"agent_id={search_agent_id}, run_id={search_run_id}"
        )

        raw_results, legacy_hit = await _read_with_legacy_fallback(
            client=client,
            layer_ids=layer_ids,
            plugin_config=plugin_config,
            op="search",
            query=query,
            limit=limit,
        )
        if legacy_hit:
            logger.info(f"[Memory] 层级 {layer} 触发旧作用域兼容读取")
        logger.info(
            f"[Memory] 层级 {layer} 搜索返回 {len(raw_results) if raw_results else 0} 条结果"
        )
        merged_results.extend(
            _annotate_results(raw_results, layer_ids["layer"], seen_ids)
        )

    merged_results.sort(
        key=lambda item: _get_combined_score(
            item, importance_weight=plugin_config.IMPORTANCE_WEIGHT
        ),
        reverse=True,
    )
    merged_results = merged_results[:limit]
    logger.info(f"[Memory] 搜索合并后共 {len(merged_results)} 条结果")
    formatted = format_search_output(
        merged_results,
        threshold=plugin_config.MEMORY_SEARCH_SCORE_THRESHOLD,
        importance_weight=plugin_config.IMPORTANCE_WEIGHT,
    )
    return "🔍 搜索结果：\n" + (formatted.get("text") or "(无结果)")


async def _command_add(
    scope: MemoryScope,
    memory_text: str,
    preferred_layer: Optional[str],
    metadata: Dict[str, Any],
) -> str:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return _format_command_error("mem0 client init failed，检查插件配置。")
    if not scope.has_scope():
        return _format_command_error("缺少 user_id/agent_id/run_id，无法写入记忆。")

    target_layer = scope.pick_layer(
        preferred=preferred_layer,
        enable_session_layer=plugin_config.SESSION_ISOLATION,
        enable_agent_layer=plugin_config.ENABLE_AGENT_SCOPE,
        prefer_long_term=True,
    )
    layer_ids = _resolve_layer_ids(scope, target_layer or "", plugin_config)
    if layer_ids is None:
        return _format_command_error(
            "未能确定可用的记忆层级，请提供 layer 或 user_id/agent_id/run_id。"
        )

    try:
        add_kwargs: Dict[str, Any] = {
            "metadata": metadata or {},
            "infer": False,
        }
        _uid = (
            layer_ids["user_id"]
            if (plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "global")
            else None
        )
        _aid = (
            layer_ids["agent_id"]
            if (plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "persona")
            else None
        )
        _rid = layer_ids["run_id"]
        if _uid is not None:
            add_kwargs["user_id"] = _uid
        if _aid is not None:
            add_kwargs["agent_id"] = _aid
        if _rid is not None:
            add_kwargs["run_id"] = _rid
        result = await asyncio.to_thread(client.add, memory_text, **add_kwargs)
    except Exception as exc:  # pragma: no cover
        logger.error(f"添加记忆失败: {exc}")
        return _format_command_error(str(exc))

    formatted = format_add_output(result)
    layer_label = layer_ids.get("layer") or target_layer or "unknown"
    return f"✅ 已添加至 {layer_label} 层：{formatted}"


# ============ 命令组注册 ===============

mem_group = plugin.mount_command_group(
    name="mem",
    description="记忆管理指令组",
    permission=CommandPermission.PUBLIC,
    category="记忆",
)


@mem_group.command(
    name="list",
    description="列出当前作用域的记忆",
    aliases=["ls"],
    usage="mem.list [layer=global|persona|conversation] [tags=TAG1,TAG2] [user=xxx] [agent=xxx] [run=xxx]",
)
async def mem_list_cmd(
    context: CommandExecutionContext,
    layer: Annotated[str, Arg("层级过滤", positional=True)] = "",
    tags: Annotated[str, Arg("标签过滤（逗号分隔）")] = "",
    user: Annotated[str, Arg("用户作用域ID")] = "",
    agent: Annotated[str, Arg("人设作用域ID")] = "",
    run: Annotated[str, Arg("会话作用域ID")] = "",
) -> CommandResponse:
    options: Dict[str, str] = {}
    if layer:
        options["layer"] = layer
    if user:
        options["user"] = user
    if agent:
        options["agent"] = agent
    if run:
        options["run"] = run
    scope = _build_scope_from_context(context, options)
    parsed_layers = _parse_layers(layer) if layer else None
    parsed_tags = _parse_tags(tags) if tags else None
    message_text = await _command_list_memory(
        scope, layers=parsed_layers, tags=parsed_tags
    )
    return CmdCtl.success(message_text)


@mem_group.command(
    name="search",
    description="语义搜索记忆",
    aliases=["s"],
    usage="mem.search <query> [layer=xxx] [limit=5] [user=xxx] [agent=xxx] [run=xxx]",
)
async def mem_search_cmd(
    context: CommandExecutionContext,
    query: Annotated[str, Arg("搜索关键词", positional=True, greedy=True)] = "",
    layer: Annotated[str, Arg("层级过滤")] = "",
    limit: Annotated[int, Arg("返回数量上限", range=(1, 50))] = 5,
    user: Annotated[str, Arg("用户作用域ID")] = "",
    agent: Annotated[str, Arg("人设作用域ID")] = "",
    run: Annotated[str, Arg("会话作用域ID")] = "",
) -> CommandResponse:
    if not query:
        return CmdCtl.failed("用法: mem.search <query> [layer=xxx] [limit=5]")
    options: Dict[str, str] = {}
    if user:
        options["user"] = user
    if agent:
        options["agent"] = agent
    if run:
        options["run"] = run
    scope = _build_scope_from_context(context, options)
    parsed_layers = _parse_layers(layer) if layer else None
    message_text = await _command_search(
        scope, query=query, layers=parsed_layers, limit=limit
    )
    return CmdCtl.success(message_text)


@mem_group.command(
    name="add",
    description="添加一条记忆",
    aliases=["a"],
    usage="mem.add <文本> [layer=xxx] [tag=TYPE] [user=xxx] [agent=xxx] [run=xxx]",
)
async def mem_add_cmd(
    context: CommandExecutionContext,
    text: Annotated[str, Arg("记忆内容", positional=True, greedy=True)] = "",
    layer: Annotated[str, Arg("目标层级")] = "",
    tag: Annotated[str, Arg("记忆标签")] = "",
    user: Annotated[str, Arg("用户作用域ID")] = "",
    agent: Annotated[str, Arg("人设作用域ID")] = "",
    run: Annotated[str, Arg("会话作用域ID")] = "",
) -> CommandResponse:
    if not text:
        return CmdCtl.failed("用法: mem.add <文本> [layer=xxx] [tag=TYPE]")
    options: Dict[str, str] = {}
    if tag:
        options["tag"] = tag
    if user:
        options["user"] = user
    if agent:
        options["agent"] = agent
    if run:
        options["run"] = run
    scope = _build_scope_from_context(context, options)
    metadata = _parse_metadata(options)
    preferred_layer = layer if layer else None
    message_text = await _command_add(
        scope, memory_text=text, preferred_layer=preferred_layer, metadata=metadata
    )
    return CmdCtl.success(message_text)


@mem_group.command(
    name="delete",
    description="删除单条记忆",
    aliases=["del", "rm"],
    usage="mem.delete <memory_id>",
)
async def mem_delete_cmd(
    context: CommandExecutionContext,
    memory_id: Annotated[str, Arg("记忆ID", positional=True)] = "",
) -> CommandResponse:
    if not memory_id:
        return CmdCtl.failed("用法: mem.delete <memory_id>")
    message_text = await _command_delete_memory(memory_id)
    return CmdCtl.success(message_text)


@mem_group.command(
    name="edit",
    description="编辑记忆内容",
    aliases=["e"],
    usage="mem.edit <memory_id> <new_text>",
)
async def mem_edit_cmd(
    context: CommandExecutionContext,
    memory_id: Annotated[str, Arg("记忆ID", positional=True)] = "",
    new_text: Annotated[str, Arg("新的记忆内容", positional=True, greedy=True)] = "",
) -> CommandResponse:
    if not memory_id:
        return CmdCtl.failed("用法: mem.edit <memory_id> <new_text>")
    if not new_text:
        return CmdCtl.failed("用法: mem.edit <memory_id> <new_text>")
    client = await get_mem0_client()
    if client is None:
        return CmdCtl.failed("记忆服务未初始化")
    try:
        _fire_and_forget(asyncio.to_thread(client.update, memory_id, new_text))
        return CmdCtl.success(f"记忆 {memory_id} 已更新（后台处理中）")
    except Exception as exc:
        return CmdCtl.failed(f"更新失败: {exc}")


@mem_group.command(
    name="clear",
    description="清空指定层级的全部记忆（危险操作）",
    aliases=["purge"],
    usage="mem.clear [layer=conversation|persona|global] [user=xxx] [agent=xxx] [run=xxx]",
    permission=CommandPermission.ADVANCED,
)
async def mem_clear_cmd(
    context: CommandExecutionContext,
    layer: Annotated[str, Arg("目标层级", positional=True)] = "",
    user: Annotated[str, Arg("用户作用域ID")] = "",
    agent: Annotated[str, Arg("人设作用域ID")] = "",
    run: Annotated[str, Arg("会话作用域ID")] = "",
) -> CommandResponse:
    options: Dict[str, str] = {}
    if user:
        options["user"] = user
    if agent:
        options["agent"] = agent
    if run:
        options["run"] = run
    scope = _build_scope_from_context(context, options)
    parsed_layers = _parse_layers(layer) if layer else None
    message_text = await _command_clear_memory(scope, layers=parsed_layers)
    return CmdCtl.success(message_text)


@mem_group.command(
    name="history",
    description="查看单条记忆的历史版本",
    aliases=["hist"],
    usage="mem.history <memory_id>",
)
async def mem_history_cmd(
    context: CommandExecutionContext,
    memory_id: Annotated[str, Arg("记忆ID", positional=True)] = "",
) -> CommandResponse:
    if not memory_id:
        return CmdCtl.failed("用法: mem.history <memory_id>")
    message_text = await _command_history(memory_id)
    return CmdCtl.success(message_text)


@mem_group.command(
    name="debug",
    description="显示当前作用域调试信息",
    permission=CommandPermission.SUPER_USER,
    internal=True,
)
async def mem_debug_cmd(
    context: CommandExecutionContext,
) -> CommandResponse:
    options: Dict[str, str] = {}
    scope = _build_scope_from_context(context, options)
    debug_info = (
        f"🔍 调试信息：\n"
        f"context.user_id = {context.user_id}\n"
        f"context.chat_key = {context.chat_key}\n"
        f"context.adapter_key = {context.adapter_key}\n"
        f"scope.user_id = {scope.user_id}\n"
        f"scope.agent_id = {scope.agent_id}\n"
        f"scope.run_id = {scope.run_id}\n"
        f"scope.has_scope() = {scope.has_scope()}"
    )
    return CmdCtl.success(debug_info)
