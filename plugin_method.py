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
)
from .mem0_utils import get_mem0_client
from .plugin import get_memory_config, plugin
from .utils import MemoryScope, decode_id, get_preset_id, resolve_memory_scope
from nekro_agent.models.db_chat_message import DBChatMessage
from .pre_search_utils import build_pre_search_query, convert_db_messages_to_dict


_MIGRATION_IN_FLIGHT: Set[Tuple[Optional[str], Optional[str], Optional[str], str]] = (
    set()
)


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
) -> List[str]:
    # 当用户显式提供 layers 时，这里进行标准化与校验，避免后续出现静默跳过的无效层级。
    if layers:
        normalized_layers: List[str] = []
        for layer in layers:
            # 使用 scope.layer_ids 来判断层级是否有效，并获取规范化后的层级名称（如果有）
            layer_info = scope.layer_ids(
                layer,
                enable_agent_layer=agent_enabled,
                bind_persona_to_user=bind_persona_to_user,
            )
            if not layer_info:
                continue
            canonical_name = layer_info.get("layer", layer)
            if canonical_name not in normalized_layers:
                normalized_layers.append(canonical_name)
        if normalized_layers:
            return normalized_layers

    # Derive the default order once so we can both validate `preferred`
    # and provide a sensible fallback when it is invalid.
    default_order = scope.default_layer_order(
        enable_session_layer=session_enabled,
        enable_agent_layer=agent_enabled,
        prefer_long_term=prefer_long_term,
    )

    if preferred:
        # Normalize and validate preferred layer name against known layers.
        normalized_preferred = preferred.strip()
        normalized_lower = normalized_preferred.lower()
        for layer_name in default_order:
            if layer_name.lower() == normalized_lower:
                # Use the canonical layer name from default_order.
                return [layer_name]

        # If we reach here, the preferred layer is not recognized.
        # Log and fall back to the default order instead of returning
        # an invalid layer that would be silently skipped later.
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

        await asyncio.to_thread(
            client.add,
            memory_text,
            user_id=target_layer_ids["user_id"],
            agent_id=target_layer_ids["agent_id"],
            run_id=target_layer_ids["run_id"],
            metadata=metadata,
            infer=False,
        )
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
        primary_raw = await asyncio.to_thread(
            client.search,
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
            legacy_raw = await asyncio.to_thread(
                client.search,
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


@plugin.mount_init_method()
async def init_plugin() -> None:
    logger.info("记忆插件初始化中...")
    await get_mem0_client()


@plugin.mount_sandbox_method(
    SandboxMethodType.BEHAVIOR,
    name="添加记忆",
    description=(
        "为用户的个人资料添加一条新记忆，添加的记忆与该用户相关。"
        "此操作为非阻塞操作，调用后立即返回，实际写入在后台完成，可以和发送消息写在同一个代码块中。"
        "调用约定：沙盒内首参传 _ctx；独立脚本首参传 None 并显式提供 user_id/agent_id/run_id（否则直接写 _ctx 会 NameError）。"
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
) -> Dict[str, Any]:
    """
    添加记忆到指定的记忆层级（非阻塞，立即返回）。

    调用约定：
    - 沙盒内：必须传入运行时注入的 _ctx（第一个参数）。
    - 沙盒外独立脚本：若无 AgentCtx，可传 None，但需显式提供 user_id/agent_id/run_id 中至少一个。

    此函数会立即返回成功状态，实际的向量数据库写入在后台异步完成，不会阻塞后续代码执行。
    因此可以安全地与 send_text 等消息发送函数写在同一个代码块中。

    ⚠️ 重要：三层记忆模型的隔离标识符
    - conversation 层：使用 run_id（会话ID），记忆仅在当前会话内有效
    - persona 层：使用 agent_id（人设ID），记忆与特定人设绑定，在该人设的所有会话间共享
    - global 层：使用 user_id（用户ID），记忆跨人设和会话，属于用户本人

    参数说明：
        memory: 要添加的记忆内容（字符串或字典）
        user_id: 用户ID（仅在 global 层有效）
        agent_id: 人设/助理ID（仅在 persona 层有效）
        run_id: 会话ID（仅在 conversation 层有效）
        scope_level: 目标层级，可选值：conversation/persona/global
        metadata: 可选的元数据，如 {"TYPE": "PREFERENCES", "category": "hobby"}

    示例：
        # 添加人设级记忆（跨会话共享）
        await add_memory(_ctx, "喜欢科幻电影", agent_id="persona_001", scope_level="persona")

        # 添加用户级记忆（跨人设共享）
        await add_memory(_ctx, "用户真实姓名：张三", user_id="user-123", scope_level="global")

        # 添加会话级记忆（仅当前对话）
        await add_memory(_ctx, "当前讨论主题：量子物理", run_id="chat-456", scope_level="conversation")
    """
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(
        _ctx, user_id=user_id, agent_id=agent_id, run_id=run_id
    )

    # 调试日志：记录写入作用域
    logger.info(
        f"[Memory] 添加记忆 - scope: user_id={scope.user_id}, agent_id={scope.agent_id}, "
        f"run_id={scope.run_id}, preset_title={scope.preset_title}, "
        f"参数: user_id={user_id}, agent_id={agent_id}, run_id={run_id}, scope_level={scope_level}"
    )

    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法写入记忆"}

    target_layer = scope.pick_layer(
        preferred=scope_level,
        enable_session_layer=plugin_config.SESSION_ISOLATION,
        enable_agent_layer=plugin_config.ENABLE_AGENT_SCOPE,
        prefer_long_term=True,
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
    _fire_and_forget(
        asyncio.to_thread(
            client.add,
            memory,
            user_id=layer_ids["user_id"],
            agent_id=layer_ids["agent_id"],
            run_id=layer_ids["run_id"],
            metadata=metadata or {},
            infer=False,
        )
    )
    return {"ok": True, "layer": layer_ids["layer"], "message": "记忆已提交写入"}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="搜索记忆",
    description=(
        "根据查询语句搜索用户记忆。"
        "此操作会自动中断当前 Agent 的生成，等待向量数据库返回结果后，继续生成后续内容。"
        "调用约定：沙盒内首参传 _ctx；独立脚本首参传 None（不要写 search_memory(_ctx, ...) 以免 NameError）。"
        "【注意】如果返回内容过长导致截断（如遇到 view_str_content 截断提示），请缩小 limit 行范围或自行提取概要内容避免全文打印。"
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
) -> Dict[str, Any]:
    """
    按层级搜索记忆，支持多层级聚合搜索。

    语义边界（非常重要）：
    - search_memory 是“语义检索”，适合“我喜欢什么/之前提过XX吗”这类具体查询。
    - 若目的是“列出全部记忆/所有记忆”，请使用 get_all_memory，而不是 search_memory。
      使用“所有记忆/全部记忆”等泛化 query 进行语义检索，可能因相似度机制返回空结果。

    调用约定：
    - 沙盒内：必须传入运行时注入的 _ctx（第一个参数）。
    - 沙盒外独立脚本：若无 AgentCtx，可传 None，但需显式提供 user_id/agent_id/run_id 中至少一个。

    ⚠️ 重要：层级搜索的隔离标识符
    - 搜索 conversation 层：需要提供 run_id（会话ID）
    - 搜索 persona 层：需要提供 agent_id（人设ID）
    - 搜索 global 层：需要提供 user_id（用户ID）
    - 多层搜索：提供对应层级所需的所有标识符，结果会按相关度排序去重

    💡 截断处理提示：若是使用时遇到 view_str_content 返回内容被截断（提示缩减 max_len），请减少 limit 参数，或者不要直接打印完整结果字典，而是提取并打印必要的精简字段。

    参数说明：
        query: 搜索查询文本（支持语义搜索）
        user_id: 用户ID（用于搜索 global 层）
        agent_id: 人设ID（用于搜索 persona 层）
        run_id: 会话ID（用于搜索 conversation 层）
        scope_level: 单一层级搜索，可选值：conversation/persona/global
        layers: 多层级搜索列表，如 ["persona", "global"]
        limit: 返回结果数量上限

    示例：
        # 在人设层级搜索（需要 agent_id）
        await search_memory(_ctx, "喜欢什么", agent_id="persona_001", layers=["persona"])

        # 跨多个层级搜索（需要对应的标识符）
        await search_memory(_ctx, "偏好", agent_id="persona_001", user_id="user-123", layers=["persona", "global"], limit=8)

        # 单层搜索（自动使用上下文中的标识符）
        await search_memory(_ctx, "历史记录", scope_level="conversation")

        # 列出全部记忆（请改用 get_all_memory）
        await get_all_memory(_ctx, agent_id="persona_001", user_id="user-123", layers=["persona", "global"])
    """
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(
        _ctx, user_id=user_id, agent_id=agent_id, run_id=run_id
    )
    if not scope.has_scope():
        return {
            "ok": False,
            "error": "缺少可用的 user_id/agent_id/run_id，无法搜索记忆",
        }

    layer_order = _build_layer_order(
        scope,
        layers=layers,
        preferred=scope_level,
        session_enabled=plugin_config.SESSION_ISOLATION,
        agent_enabled=plugin_config.ENABLE_AGENT_SCOPE,
        bind_persona_to_user=plugin_config.PERSONA_BIND_USER,
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

    merged_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    merged_results = merged_results[:limit]

    formatted = format_search_output(
        merged_results, threshold=plugin_config.MEMORY_SEARCH_SCORE_THRESHOLD
    )
    return {"ok": True, **formatted}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="获取记忆列表",
    description=(
        "获取指定作用域（user/agent/run）的全部记忆，可按标签过滤。"
        "此操作会自动中断当前 Agent 的生成，等待向量数据库返回结果后，继续生成后续内容。"
        "调用约定：沙盒内首参传 _ctx；独立脚本首参传 None 并显式提供 user_id/agent_id/run_id（否则直接写 _ctx 会 NameError）。"
        "【注意】当记忆条目过多时可能被截断（如遇到 view_str_content 截断提示），建议按 tags 过滤，或自行提取概要字段避免直接全量打印字典。"
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
    获取指定层级的全部记忆，支持标签过滤。

    调用约定：
    - 沙盒内：必须传入运行时注入的 _ctx（第一个参数）。
    - 沙盒外独立脚本：若无 AgentCtx，可传 None，但需显式提供 user_id/agent_id/run_id 中至少一个。

    ⚠️ 重要：层级获取的隔离标识符
    - 获取 conversation 层：需要提供 run_id（会话ID）
    - 获取 persona 层：需要提供 agent_id（人设ID）- ⚠️ 常见错误：不要用 user_id！
    - 获取 global 层：需要提供 user_id（用户ID）
    - 多层获取：提供对应层级所需的所有标识符

    💡 截断处理提示：若是遇到 view_str_content 返回内容被截断（提示缩减 max_len），建议根据 tags 过滤缩小范围，或者在代码中循环获取概要字段，不要直接打印完整结果。

    参数说明：
        user_id: 用户ID（仅用于获取 global 层记忆）
        agent_id: 人设ID（仅用于获取 persona 层记忆）
        run_id: 会话ID（仅用于获取 conversation 层记忆）
        scope_level: 单一层级，可选值：conversation/persona/global
        layers: 多层级列表，如 ["persona", "global"]
        tags: 标签过滤器，如 ["PREFERENCES", "FACTS"]

    示例：
        # ❌ 错误：使用 user_id 获取 persona 层（会返回空）
        await get_all_memory(_ctx, user_id="user-123", layers=["persona"])

        # ✅ 正确：使用 agent_id 获取 persona 层
        await get_all_memory(_ctx, agent_id="persona_001", layers=["persona"])

        # ✅ 正确：获取用户的全局记忆
        await get_all_memory(_ctx, user_id="user-123", layers=["global"])

        # ✅ 正确：跨层级获取（需要对应标识符）
        await get_all_memory(_ctx, agent_id="persona_001", user_id="user-123", layers=["persona", "global"], tags=["PREFERENCES"])
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
    description=(
        "根据记忆ID更新记忆内容。"
        "此操作为非阻塞操作，调用后立即返回，实际更新在后台完成，可以和发送消息写在同一个代码块中。"
        "调用约定：沙盒内首参传 _ctx；独立脚本首参传 None（否则直接写 _ctx 会 NameError）。"
    ),
)
async def update_memory(
    _ctx: Optional[AgentCtx],
    memory_id: str,
    new_memory: str,
) -> Dict[str, Any]:
    """
    更新指定记忆内容（跨所有层级通用，非阻塞，立即返回）。

    调用约定：
    - 沙盒内：首参传运行时注入的 _ctx。
    - 沙盒外独立脚本：首参传 None（避免直接写 _ctx 导致 NameError）。

    此函数会立即返回成功状态，实际的向量数据库更新在后台异步完成，不会阻塞后续代码执行。

    注意：memory_id 是全局唯一的，更新操作不需要指定层级或标识符。

    参数说明：
        memory_id: 记忆的唯一ID（可从 search_memory 或 get_all_memory 结果中获取）
        new_memory: 新的记忆内容

    示例：
        await update_memory(_ctx, memory_id="abc123", new_memory="改为喜欢爵士乐")
        await update_memory(None, memory_id="abc123", new_memory="改为喜欢爵士乐")
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
        "根据记忆ID删除单条记忆。当发现记忆内容已过时、不准确或与当前事实矛盾时，应主动调用此方法清理。"
        "例如：用户更正了之前的信息、用户偏好发生变化、记忆内容与新获取的信息冲突等情况。"
        "此操作为非阻塞操作，调用后立即返回，实际删除在后台完成，可以和发送消息写在同一个代码块中。"
        "调用约定：沙盒内首参传 _ctx；独立脚本首参传 None（否则直接写 _ctx 会 NameError）。"
    ),
)
async def delete_memory(
    _ctx: Optional[AgentCtx],
    memory_id: str,
) -> Dict[str, Any]:
    """
    删除单条记忆（跨所有层级通用，非阻塞，立即返回）。

    调用约定：
    - 沙盒内：首参传运行时注入的 _ctx。
    - 沙盒外独立脚本：首参传 None（避免直接写 _ctx 导致 NameError）。

    此函数会立即返回成功状态，实际的向量数据库删除在后台异步完成，不会阻塞后续代码执行。

    💡 记忆清理最佳实践：
    你应该主动清理过时的记忆，以保持记忆库的准确性。以下情况应删除旧记忆：
    - 用户主动更正了之前的信息（如"我其实不喜欢XX"→删除之前"喜欢XX"的记忆）
    - 用户偏好/状态发生变化（如换了工作、搬了家→删除旧的工作/地址记忆）
    - 记忆内容与新信息矛盾（保留最新的，删除过时的）
    - 临时性信息已过期（如"明天要开会"→会议结束后可清理）
    建议在添加新记忆前，先搜索是否存在相关的旧记忆，如有矛盾则先删除旧记忆再添加新记忆。

    注意：memory_id 是全局唯一的，删除操作不需要指定层级或标识符。

    参数说明：
        memory_id: 记忆的唯一ID（可从 search_memory 或 get_all_memory 结果中获取）

    示例：
        await delete_memory(_ctx, memory_id="abc123")
        await delete_memory(None, memory_id="abc123")
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
        "删除指定 user/agent/run 对应的全部记忆（危险操作，请谨慎使用）。"
        "此操作为非阻塞操作，调用后立即返回，实际删除在后台完成，可以和发送消息写在同一个代码块中。"
        "调用约定：沙盒内首参传 _ctx；独立脚本首参传 None 并显式提供 user_id/agent_id/run_id（否则直接写 _ctx 会 NameError）。"
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
    按层级批量删除记忆（危险操作，请谨慎使用。非阻塞，立即返回）。

    调用约定：
    - 沙盒内：必须传入运行时注入的 _ctx（第一个参数）。
    - 沙盒外独立脚本：若无 AgentCtx，可传 None，但需显式提供 user_id/agent_id/run_id 中至少一个。

    此函数会立即返回成功状态，实际的向量数据库删除在后台异步完成，不会阻塞后续代码执行。

    ⚠️ 重要：层级删除的隔离标识符
    - 删除 conversation 层：需要提供 run_id（会话ID）
    - 删除 persona 层：需要提供 agent_id（人设ID）
    - 删除 global 层：需要提供 user_id（用户ID）
    - 多层删除：提供对应层级所需的所有标识符

    参数说明：
        user_id: 用户ID（用于删除 global 层记忆）
        agent_id: 人设ID（用于删除 persona 层记忆）
        run_id: 会话ID（用于删除 conversation 层记忆）
        scope_level: 单一层级，可选值：conversation/persona/global
        layers: 多层级列表，如 ["persona", "global"]

    示例：
        # 删除特定人设的所有记忆
        await delete_all_memory(_ctx, agent_id="persona_001", layers=["persona"])

        # 删除用户的全局记忆
        await delete_all_memory(_ctx, user_id="user-123", layers=["global"])

        # 清空多个层级
        await delete_all_memory(_ctx, agent_id="persona_001", user_id="user-123", layers=["persona", "global"])
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
            await asyncio.to_thread(
                client.delete_all,
                user_id=_layer_ids["user_id"],
                agent_id=_layer_ids["agent_id"],
                run_id=_layer_ids["run_id"],
            )

        _fire_and_forget(_do_delete_all())

    if not target_layers:
        return {"ok": False, "error": "未能匹配任何可删除的层级"}
    return {"ok": True, "message": f"已提交删除作用域记忆：{', '.join(target_layers)}"}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="获取记忆历史",
    description=(
        "查看指定记忆的历史版本。"
        "此操作会自动中断当前 Agent 的生成，等待向量数据库返回结果后，继续生成后续内容。"
        "调用约定：沙盒内首参传 _ctx；独立脚本首参传 None（否则直接写 _ctx 会 NameError）。"
        "【注意】如果历史内容过长导致截断（如遇到 view_str_content 截断提示），请自行提取结果概要避免全文打印字典。"
    ),
)
async def get_memory_history(
    _ctx: Optional[AgentCtx],
    memory_id: str,
) -> Dict[str, Any]:
    """
    查看指定记忆的历史版本（跨所有层级通用）。

    调用约定：
    - 沙盒内：首参传运行时注入的 _ctx。
    - 沙盒外独立脚本：首参传 None（避免直接写 _ctx 导致 NameError）。

    💡 截断处理提示：若是遇到 view_str_content 返回内容被截断（提示缩减 max_len），请勿直接打印完整结果字典，而是提取必要的精简字段。

    注意：memory_id 是全局唯一的，查询历史不需要指定层级或标识符。

    参数说明：
        memory_id: 记忆的唯一ID（可从 search_memory 或 get_all_memory 结果中获取）

    示例：
        await get_memory_history(_ctx, memory_id="abc123")
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
        "提供命令式入口，便于在后台/网页操作：支持 add/search/list/update/delete/delete_all/history。"
        "调用约定：沙盒内首参传 _ctx；独立脚本首参传 None（否则直接写 _ctx 会 NameError）。"
    ),
)
async def memory_command(
    _ctx: Optional[AgentCtx],
    action: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    统一命令入口，便于上层做网页/后台交互调用。

    调用约定：
    - 沙盒内：首参传运行时注入的 _ctx。
    - 沙盒外独立脚本：首参传 None；并在 payload 中显式给出 user_id/agent_id/run_id 以确保作用域可解析。

    示例：
        await memory_command(_ctx, "search", {"query": "最喜欢的颜色", "user_id": "user-1"})
    """
    payload = payload or {}
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
            return None

        # 2. 生成查询
        query = build_pre_search_query(
            messages,
            config.PRE_SEARCH_QUERY_MESSAGE_COUNT,
            config.PRE_SEARCH_QUERY_MAX_LENGTH,
        )

        if not query:
            logger.debug("[PreSearch] 无法生成查询，跳过预搜索")
            return None

        logger.info(f"[PreSearch] 生成查询: {query[:100]}...")

        # 3. 解析作用域
        scope = resolve_memory_scope(_ctx)
        if not scope.has_scope():
            logger.debug("[PreSearch] 无有效作用域，跳过预搜索")
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
            return None

        logger.debug(f"[PreSearch] 搜索层级: {layer_order}")

        # 5. 获取 mem0 客户端
        client = await get_mem0_client()
        if client is None:
            logger.warning("[PreSearch] mem0 客户端初始化失败")
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
            return None

        # 7. 合并结果并去重
        merged_results: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()

        for layer_name, raw_results in layer_results:
            if raw_results is None:
                continue

            annotated = _annotate_results(raw_results, layer_name, seen_ids)
            merged_results.extend(annotated)

        if not merged_results:
            logger.debug("[PreSearch] 无搜索结果")
            return None

        # 8. 按分数排序并限制数量
        merged_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        completed_layer_count = max(1, len(layer_results))
        top_results = merged_results[
            : config.PRE_SEARCH_RESULT_LIMIT * completed_layer_count
        ]

        # 9. 格式化结果
        formatted = format_search_output(
            top_results, threshold=config.MEMORY_SEARCH_SCORE_THRESHOLD
        )

        result_text = formatted.get("text", "")
        if not result_text or result_text == "(无结果)":
            return None

        logger.info(f"[PreSearch] 成功检索到 {len(top_results)} 条记忆")
        return result_text

    except asyncio.TimeoutError:
        logger.warning(f"[PreSearch] 超时（>{config.PRE_SEARCH_TIMEOUT}s），降级")
        return None
    except Exception as exc:
        logger.warning(f"[PreSearch] 执行失败: {exc}", exc_info=True)
        return None


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
        except Exception as exc:
            # 优雅降级：任何异常都不影响基础提示
            logger.warning(f"[PreSearch] 预搜索失败，降级到基础提示: {exc}")

    scope = resolve_memory_scope(_ctx)
    layer_order = scope.default_layer_order(
        enable_session_layer=config.SESSION_ISOLATION,
        enable_agent_layer=config.ENABLE_AGENT_SCOPE,
    )
    available_layers = ", ".join(layer_order) if layer_order else "无可用层级"
    lines = [
        "你可以使用记忆插件在多个会话间维持用户/Agent的长期记忆。",
        "",
        "📌 【操作类型与调用规范】：",
        "记忆操作分为两类，请区分对待：",
        "",
        "  🟢 写操作（非阻塞，立即返回）：add_memory / update_memory / delete_memory / delete_all_memory",
        "     这些操作会立即返回，实际写入在后台完成。可以和 send_text 等消息发送写在同一个代码块中。",
        "",
        "  🟡 读操作（需要等待结果）：search_memory / get_all_memory / get_memory_history",
        "     这些操作需要等待向量数据库返回结果，可能耗时较长。",
        "     建议将读操作与发送消息分开到不同代码块中，避免因耗时过长导致执行超时。",
        "     正确做法：代码块1执行搜索 → 代码块2根据结果发送消息。",
        "",
        "✅ 可以这样写（写操作 + 发消息在一起）：",
        "  ```",
        "  await add_memory(_ctx, '用户喜欢猫')",
        "  await send_text(_ctx, '好的，我记住了！')",
        "  ```",
        "",
        "✅ 读操作建议分开代码块：",
        "  ```",
        "  # 代码块1：搜索记忆",
        "  result = await search_memory(_ctx, '用户的爱好')",
        "  ```",
        "  ```",
        "  # 代码块2：根据结果回复",
        "  await send_text(_ctx, f'根据我的记忆，你的爱好是...')",
        "  ```",
        "",
        "🔎 【search_memory 与 get_all_memory 的边界】（必须遵守）：",
        "  • search_memory：语义检索（需要具体查询意图），例如‘我喜欢什么’、‘之前提过旅行吗’。",
        "  • get_all_memory：列举记忆（获取全量/清单），例如‘列出所有记忆/全部记忆’。",
        "  • 不要用 search_memory(query='所有记忆') 来做全量列举；这会因语义相似度机制出现空结果。",
        "",
        "🧹 【记忆清理最佳实践】：",
        "你应该主动维护记忆库的准确性，及时清理过时或矛盾的记忆：",
        "  • 当用户更正信息时（如'我其实不喜欢XX'），先搜索并删除旧的错误记忆，再添加正确的",
        "  • 当用户状态变化时（如换工作、搬家），删除旧状态记忆，添加新状态",
        "  • 当发现记忆之间存在矛盾时，保留最新的，删除过时的",
        "  • 临时性信息过期后应清理（如已结束的事件、已完成的计划）",
        "  • 建议流程：搜索相关旧记忆 → 删除过时的 → 添加新记忆",
        "",
        "⚠️ 重要：三层记忆模型的隔离标识符（请务必理解）：",
        "  • conversation 层：使用 run_id，记忆仅在当前会话内有效",
        "  • persona 层：使用 agent_id（人设ID），记忆与特定人设绑定，在该人设的所有会话间共享",
        "  • global 层：使用 user_id，记忆跨人设和会话，属于用户本人",
        "",
        "❌ 常见错误：",
        "  • 不要用 user_id 操作 persona 层（会失败或返回空）",
        "  • 不要用 agent_id 操作 global 层（会失败或返回空）",
        "  • persona 层跨会话共享需要在不同会话中使用相同的 agent_id",
        "",
        "🔧 调用上下文约定（必须遵守）：",
        "  • 这些方法有两种调用形态：沙盒内传 _ctx；沙盒外独立脚本传 None。",
        "  • 沙盒内（Nekro Agent 运行时）：_ctx 由运行时自动注入，所有记忆方法都把 _ctx 作为第一个参数。",
        "  • 沙盒外独立脚本：不要写 search_memory(_ctx, ...)，应写 search_memory(None, ...)，并显式提供 user_id/agent_id/run_id。",
        "",
        "写入记忆：调用 add_memory(ctx_or_none, memory, scope_level?, user_id?, agent_id?, run_id?, metadata?)",
        "  • 写入 persona 层：add_memory(_ctx, memory, agent_id='xxx', scope_level='persona')",
        "  • 写入 global 层：add_memory(_ctx, memory, user_id='xxx', scope_level='global')",
        "  • 写入 conversation 层：add_memory(_ctx, memory, run_id='xxx', scope_level='conversation')",
        "",
        "检索记忆：调用 search_memory(ctx_or_none, query, layers?, user_id?, agent_id?, run_id?, limit?)",
        "  • 搜索 persona 层：search_memory(_ctx, query, agent_id='xxx', layers=['persona'])",
        "  • 搜索 global 层：search_memory(_ctx, query, user_id='xxx', layers=['global'])",
        "  • 跨层搜索：search_memory(_ctx, query, agent_id='xxx', user_id='xxx', layers=['persona', 'global'])",
        "  • 常见错误（独立脚本）：search_memory(_ctx, query, ...) -> NameError: _ctx is not defined",
        "  • 沙盒外调试示例：search_memory(None, query, agent_id='xxx', user_id='xxx', layers=['persona', 'global'])",
        "",
        "获取全部记忆：调用 get_all_memory(ctx_or_none, layers?, user_id?, agent_id?, run_id?, tags?)",
        "  • 获取 persona 层：get_all_memory(_ctx, agent_id='xxx', layers=['persona'])",
        "  • 获取 global 层：get_all_memory(_ctx, user_id='xxx', layers=['global'])",
        "  • 列出 persona+global 全量：get_all_memory(_ctx, agent_id='xxx', user_id='xxx', layers=['persona', 'global'])",
        "",
        "更新记忆：调用 update_memory(_ctx, memory_id, new_memory)，用于修订已存知识。",
        "删除记忆：调用 delete_memory(_ctx, memory_id) 删除单条过时/错误记忆。",
        "批量删除：调用 delete_all_memory(_ctx, layers?, user_id?, agent_id?, run_id?) 清空作用域。",
        f"当前相似度阈值: {config.MEMORY_SEARCH_SCORE_THRESHOLD}。",
        f"可用层级顺序: {available_layers}。",
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
            await asyncio.to_thread(
                client.delete_all,
                user_id=layer_ids["user_id"],
                agent_id=layer_ids["agent_id"],
                run_id=layer_ids["run_id"],
            )
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

    merged_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    merged_results = merged_results[:limit]
    logger.info(f"[Memory] 搜索合并后共 {len(merged_results)} 条结果")
    formatted = format_search_output(
        merged_results, threshold=plugin_config.MEMORY_SEARCH_SCORE_THRESHOLD
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
        result = await asyncio.to_thread(
            client.add,
            memory_text,
            user_id=layer_ids["user_id"],
            agent_id=layer_ids["agent_id"],
            run_id=layer_ids["run_id"],
            metadata=metadata or {},
            infer=False,
        )
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
