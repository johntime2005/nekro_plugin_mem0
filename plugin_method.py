"""
插件方法
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import logger
from nekro_agent.adapters.onebot_v11.matchers.command import finish_with, on_command
from nekro_agent.services.plugin.base import SandboxMethodType
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
from .utils import MemoryScope, get_preset_id, resolve_memory_scope


def _memory_identifier(item: Dict[str, Any]) -> Optional[str]:
    """提取统一的记忆ID，便于跨层去重。"""
    for key in ("id", "memory_id"):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _build_layer_order(
    scope, layers: Optional[List[str]], preferred: Optional[str], session_enabled: bool
) -> List[str]:
    # 当用户显式提供 layers 时，这里进行标准化与校验，避免后续出现静默跳过的无效层级。
    if layers:
        normalized_layers: List[str] = []
        for layer in layers:
            # 使用 scope.layer_ids 来判断层级是否有效，并获取规范化后的层级名称（如果有）
            layer_info = scope.layer_ids(layer)
            if not layer_info:
                continue
            canonical_name = layer_info.get("layer", layer)
            if canonical_name not in normalized_layers:
                normalized_layers.append(canonical_name)
        if normalized_layers:
            return normalized_layers

    # Derive the default order once so we can both validate `preferred`
    # and provide a sensible fallback when it is invalid.
    default_order = scope.default_layer_order(enable_session_layer=session_enabled)

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


def _build_scope_from_event(
    event: MessageEvent, options: Dict[str, str]
) -> MemoryScope:
    user_id = _normalize_cli_value(
        options.get("user") or options.get("u") or getattr(event, "user_id", None)
    )

    # 修复：OneBot v11 的 user_id 需要添加 "private_" 前缀，与 db_user.unique_id 保持一致
    # 这样才能匹配 Agent 写入时使用的 user_id
    if user_id and user_id.isdigit():
        user_id = f"private_{user_id}"

    # 如果需要人设/Agent隔离，可以通过 agent=xxx 传入；默认留空，与 sandbox 默认行为一致（优先会话/用户）
    agent_id = _normalize_cli_value(
        options.get("agent") or options.get("persona") or options.get("preset")
    )
    run_source = _normalize_cli_value(
        options.get("run")
        or options.get("session")
        or options.get("chat")
        or getattr(event, "group_id", None)
        or getattr(event, "channel_id", None)
        or getattr(event, "guild_id", None)
        or getattr(event, "user_id", None)
    )
    run_id = get_preset_id(run_source) if run_source else None

    # 调试日志：记录作用域构建信息
    logger.debug(
        f"[Memory] 构建作用域 - user_id={user_id}, agent_id={agent_id}, run_id={run_id}, "
        f"run_source={run_source}, event.user_id={getattr(event, 'user_id', None)}, "
        f"event.group_id={getattr(event, 'group_id', None)}"
    )

    return MemoryScope(user_id=user_id, agent_id=agent_id, run_id=run_id)


def _format_command_error(message: str) -> str:
    return f"❌ {message}"


@plugin.mount_init_method()
async def init_plugin() -> None:
    logger.info("记忆插件初始化中...")


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="添加记忆",
    description="为用户的个人资料添加一条新记忆，添加的记忆与该用户相关",
)
async def add_memory(
    _ctx: AgentCtx,
    memory: Any,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    scope_level: Optional[str] = None,
) -> Dict[str, Any]:
    """
    添加记忆到指定的记忆层级。

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
        preferred=scope_level, enable_session_layer=plugin_config.SESSION_ISOLATION
    )
    logger.info(
        f"[Memory] 选择层级 - target_layer={target_layer}, SESSION_ISOLATION={plugin_config.SESSION_ISOLATION}, "
        f"ENABLE_AGENT_SCOPE={plugin_config.ENABLE_AGENT_SCOPE}"
    )

    layer_ids = scope.layer_ids(target_layer or "")
    if layer_ids is None:
        return {
            "ok": False,
            "error": "未能确定可用的记忆层级，请提供 scope_level 或 user_id/agent_id/run_id",
        }

    result = client.add(
        memory,
        user_id=layer_ids["user_id"]
        if plugin_config.ENABLE_AGENT_SCOPE or target_layer == "global"
        else None,
        agent_id=layer_ids["agent_id"]
        if plugin_config.ENABLE_AGENT_SCOPE or target_layer == "persona"
        else None,
        run_id=layer_ids["run_id"],
        metadata=metadata or {},
    )
    formatted = format_add_output(result)
    formatted["layer"] = layer_ids["layer"]
    return formatted


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="搜索记忆",
    description="根据查询语句搜索用户记忆",
)
async def search_memory(
    _ctx: AgentCtx,
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

    ⚠️ 重要：层级搜索的隔离标识符
    - 搜索 conversation 层：需要提供 run_id（会话ID）
    - 搜索 persona 层：需要提供 agent_id（人设ID）
    - 搜索 global 层：需要提供 user_id（用户ID）
    - 多层搜索：提供对应层级所需的所有标识符，结果会按相关度排序去重

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
    )
    if not layer_order:
        return {"ok": False, "error": "未找到可搜索的层级"}

    merged_results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for layer in layer_order:
        layer_ids = scope.layer_ids(layer)
        if not layer_ids:
            continue
        search_run_id = (
            layer_ids["run_id"]
            if plugin_config.SESSION_ISOLATION or layer_ids["layer"] == "conversation"
            else None
        )
        search_agent_id = (
            layer_ids["agent_id"]
            if plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "persona"
            else None
        )
        search_user_id = (
            layer_ids["user_id"] if layer_ids["layer"] == "global" else None
        )

        # mem0 v1.0.0 compatibility: threshold is removed, we rely on post-filtering
        search_kwargs = {
            "query": query,
            "user_id": search_user_id,
            "agent_id": search_agent_id,
            "run_id": search_run_id,
            "limit": limit,
        }

        # NOTE: Do NOT use filters for score/threshold for OSS backends (Qdrant/Chroma)
        # as they don't support dynamic score filtering in the search query.
        # We handle threshold filtering in format_search_output instead.

        raw_results = client.search(**search_kwargs)
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
    description="获取指定作用域（user/agent/run）的全部记忆，可按标签过滤",
)
async def get_all_memory(
    _ctx: AgentCtx,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    scope_level: Optional[str] = None,
    layers: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    获取指定层级的全部记忆，支持标签过滤。

    ⚠️ 重要：层级获取的隔离标识符
    - 获取 conversation 层：需要提供 run_id（会话ID）
    - 获取 persona 层：需要提供 agent_id（人设ID）- ⚠️ 常见错误：不要用 user_id！
    - 获取 global 层：需要提供 user_id（用户ID）
    - 多层获取：提供对应层级所需的所有标识符

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
    )
    if not layer_order:
        return {"ok": False, "error": "未找到可获取的层级"}

    merged_results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for layer in layer_order:
        layer_ids = scope.layer_ids(layer)
        if not layer_ids:
            continue
        raw = client.get_all(
            user_id=layer_ids["user_id"] if layer_ids["layer"] == "global" else None,
            agent_id=layer_ids["agent_id"]
            if plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "persona"
            else None,
            run_id=layer_ids["run_id"]
            if layer_ids["layer"] == "conversation"
            else None,
        )
        merged_results.extend(_annotate_results(raw, layer_ids["layer"], seen_ids))

    formatted = format_get_all_output(merged_results, tags=tags)
    return {"ok": True, **formatted}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="更新记忆",
    description="根据记忆ID更新记忆内容",
)
async def update_memory(
    _ctx: AgentCtx,
    memory_id: str,
    new_memory: str,
) -> Dict[str, Any]:
    """
    更新指定记忆内容（跨所有层级通用）。

    注意：memory_id 是全局唯一的，更新操作不需要指定层级或标识符。

    参数说明：
        memory_id: 记忆的唯一ID（可从 search_memory 或 get_all_memory 结果中获取）
        new_memory: 新的记忆内容

    示例：
        await update_memory(_ctx, memory_id="abc123", new_memory="改为喜欢爵士乐")
    """
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    try:
        result = client.update(memory_id, new_memory)
    except Exception as exc:  # pragma: no cover - mem0内部异常透出
        logger.error(f"更新记忆失败: {exc}")
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": result}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="删除记忆",
    description="根据记忆ID删除单条记忆",
)
async def delete_memory(
    _ctx: AgentCtx,
    memory_id: str,
) -> Dict[str, Any]:
    """
    删除单条记忆（跨所有层级通用）。

    注意：memory_id 是全局唯一的，删除操作不需要指定层级或标识符。

    参数说明：
        memory_id: 记忆的唯一ID（可从 search_memory 或 get_all_memory 结果中获取）

    示例：
        await delete_memory(_ctx, memory_id="abc123")
    """
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    try:
        result = client.delete(memory_id)
    except Exception as exc:  # pragma: no cover
        logger.error(f"删除记忆失败: {exc}")
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": result}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="删除作用域记忆",
    description="删除指定 user/agent/run 对应的全部记忆",
)
async def delete_all_memory(
    _ctx: AgentCtx,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    scope_level: Optional[str] = None,
    layers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    按层级批量删除记忆（危险操作，请谨慎使用）。

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
    )
    if not layer_order:
        return {"ok": False, "error": "未找到可删除的层级"}

    deleted_layers: List[str] = []
    try:
        for layer in layer_order:
            layer_ids = scope.layer_ids(layer)
            if not layer_ids:
                continue
            client.delete_all(
                user_id=layer_ids["user_id"]
                if layer_ids["layer"] == "global"
                else None,
                agent_id=layer_ids["agent_id"]
                if plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "persona"
                else None,
                run_id=layer_ids["run_id"]
                if layer_ids["layer"] == "conversation"
                else None,
            )
            deleted_layers.append(layer_ids["layer"])
    except Exception as exc:  # pragma: no cover
        logger.error(f"删除全部记忆失败: {exc}")
        return {"ok": False, "error": str(exc)}

    if not deleted_layers:
        return {"ok": False, "error": "未能匹配任何可删除的层级"}
    return {"ok": True, "message": f"已删除指定作用域记忆：{', '.join(deleted_layers)}"}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="获取记忆历史",
    description="查看指定记忆的历史版本",
)
async def get_memory_history(
    _ctx: AgentCtx,
    memory_id: str,
) -> Dict[str, Any]:
    """
    查看指定记忆的历史版本（跨所有层级通用）。

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
        results = client.history(memory_id)
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
    SandboxMethodType.AGENT,
    name="记忆指令面板",
    description="提供命令式入口，便于在后台/网页操作：支持 add/search/list/update/delete/delete_all/history",
)
async def memory_command(
    _ctx: AgentCtx,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    统一命令入口，便于上层做网页/后台交互调用。

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


@plugin.mount_prompt_inject_method(
    name="memory_layer_hint",
    description="为LLM注入可用的长期记忆能力提示，包含跨用户/Agent/会话的存取方式",
)
async def inject_memory_prompt(_ctx: AgentCtx) -> str:
    config = get_memory_config()
    scope = resolve_memory_scope(_ctx)
    layer_order = scope.default_layer_order(
        enable_session_layer=config.SESSION_ISOLATION
    )
    available_layers = ", ".join(layer_order) if layer_order else "无可用层级"

    lines = [
        "你可以使用记忆插件在多个会话间维持用户/Agent的长期记忆。",
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
        "写入记忆：调用 add_memory(memory, scope_level, user_id?, agent_id?, run_id?, metadata?)",
        "  • 写入 persona 层：add_memory(memory, agent_id='xxx', scope_level='persona')",
        "  • 写入 global 层：add_memory(memory, user_id='xxx', scope_level='global')",
        "  • 写入 conversation 层：add_memory(memory, run_id='xxx', scope_level='conversation')",
        "",
        "检索记忆：调用 search_memory(query, layers?, user_id?, agent_id?, run_id?, limit?)",
        "  • 搜索 persona 层：search_memory(query, agent_id='xxx', layers=['persona'])",
        "  • 搜索 global 层：search_memory(query, user_id='xxx', layers=['global'])",
        "  • 跨层搜索：search_memory(query, agent_id='xxx', user_id='xxx', layers=['persona', 'global'])",
        "",
        "获取全部记忆：调用 get_all_memory(layers?, user_id?, agent_id?, run_id?, tags?)",
        "  • 获取 persona 层：get_all_memory(agent_id='xxx', layers=['persona'])",
        "  • 获取 global 层：get_all_memory(user_id='xxx', layers=['global'])",
        "",
        "更新记忆：调用 update_memory(memory_id, new_memory)，用于修订已存知识。",
        "删除记忆：调用 delete_memory(memory_id) 删除单条，或 delete_all_memory(layers?, user_id?, agent_id?, run_id?) 清空作用域。",
        f"当前相似度阈值: {config.MEMORY_SEARCH_SCORE_THRESHOLD}。",
        f"可用层级顺序: {available_layers}。",
    ]

    if config.ENABLE_AGENT_SCOPE:
        lines.append(
            "已启用 Agent/人设 级记忆：同一人设可在多会话间共享知识，不同人设彼此隔离。"
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

    return "\n".join(lines)


# ============ 聊天指令：/mem ===============

MEMORY_HELP_TEXT = """🧠 记忆指令帮助
用法示例：
- mem list                     # 列出当前会话/用户的记忆
- mem list layer=global        # 仅查看全局层
- mem delete <memory_id>       # 删除单条
- mem clear                    # 按默认层级依次清空
- mem clear layer=conversation # 只清空会话层
- mem history <memory_id>      # 查看历史
- mem search <query>           # 语义搜索（默认按层级顺序）
- mem add <文本> tag=TYPE      # 添加记忆，可选 layer=conversation/persona/global
可选参数：user=xxx agent=xxx run=xxx layer=xxx tag=TYPE meta.xxx=val
"""


memory_command_entry = on_command(
    "mem", aliases={"memory", "记忆"}, priority=5, block=True
)


async def _command_list_memory(
    scope: MemoryScope, layers: Optional[List[str]], tags: Optional[List[str]]
) -> str:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return _format_command_error("mem0 client init failed，检查插件配置。")

    # 调试日志：记录作用域状态
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
    )
    logger.info(
        f"[Memory] 层级顺序: {layer_order}, SESSION_ISOLATION={plugin_config.SESSION_ISOLATION}"
    )

    if not layer_order:
        return _format_command_error("未找到可获取的层级。")

    merged_results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for layer in layer_order:
        layer_ids = scope.layer_ids(layer)
        if not layer_ids:
            logger.warning(f"[Memory] 跳过层级 {layer}，layer_ids 为空")
            continue

        # 调试日志：记录查询参数
        query_user_id = layer_ids["user_id"] if layer_ids["layer"] == "global" else None
        query_agent_id = (
            layer_ids["agent_id"]
            if plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "persona"
            else None
        )
        query_run_id = (
            layer_ids["run_id"] if layer_ids["layer"] == "conversation" else None
        )

        logger.info(
            f"[Memory] 查询层级 {layer} - user_id={query_user_id}, "
            f"agent_id={query_agent_id}, run_id={query_run_id}, "
            f"ENABLE_AGENT_SCOPE={plugin_config.ENABLE_AGENT_SCOPE}"
        )

        raw = client.get_all(
            user_id=query_user_id,
            agent_id=query_agent_id,
            run_id=query_run_id,
        )
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
        client.delete(memory_id)
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
    )
    if not layer_order:
        return _format_command_error("未找到可删除的层级。")

    deleted_layers: List[str] = []
    try:
        for layer in layer_order:
            layer_ids = scope.layer_ids(layer)
            if not layer_ids:
                continue
            client.delete_all(
                user_id=layer_ids["user_id"]
                if layer_ids["layer"] == "global"
                else None,
                agent_id=layer_ids["agent_id"]
                if plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "persona"
                else None,
                run_id=layer_ids["run_id"]
                if layer_ids["layer"] == "conversation"
                else None,
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
        results = client.history(memory_id)
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

    # 调试日志：记录搜索参数
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
    )
    logger.info(
        f"[Memory] 搜索层级顺序: {layer_order}, SESSION_ISOLATION={plugin_config.SESSION_ISOLATION}"
    )

    if not layer_order:
        return _format_command_error("未找到可搜索的层级。")

    merged_results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for layer in layer_order:
        layer_ids = scope.layer_ids(layer)
        if not layer_ids:
            logger.warning(f"[Memory] 搜索跳过层级 {layer}，layer_ids 为空")
            continue
        search_run_id = (
            layer_ids["run_id"]
            if plugin_config.SESSION_ISOLATION or layer_ids["layer"] == "conversation"
            else None
        )
        search_agent_id = (
            layer_ids["agent_id"]
            if plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "persona"
            else None
        )
        search_user_id = (
            layer_ids["user_id"] if layer_ids["layer"] == "global" else None
        )

        logger.info(
            f"[Memory] 在层级 {layer} 搜索 - user_id={search_user_id}, "
            f"agent_id={search_agent_id}, run_id={search_run_id}"
        )

        # mem0 v1.0.0 compatibility: threshold is removed, we rely on post-filtering
        search_kwargs = {
            "query": query,
            "user_id": search_user_id,
            "agent_id": search_agent_id,
            "run_id": search_run_id,
            "limit": limit,
        }

        # NOTE: Do NOT use filters for score/threshold for OSS backends (Qdrant/Chroma)
        # as they don't support dynamic score filtering in the search query.
        # We handle threshold filtering in format_search_output instead.

        raw_results = client.search(**search_kwargs)
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
        preferred=preferred_layer, enable_session_layer=plugin_config.SESSION_ISOLATION
    )
    layer_ids = scope.layer_ids(target_layer or "")
    if layer_ids is None:
        return _format_command_error(
            "未能确定可用的记忆层级，请提供 layer 或 user_id/agent_id/run_id。"
        )

    try:
        result = client.add(
            memory_text,
            user_id=layer_ids["user_id"]
            if plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "global"
            else None,
            agent_id=layer_ids["agent_id"]
            if plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "persona"
            else None,
            run_id=layer_ids["run_id"],
            metadata=metadata or {},
        )
    except Exception as exc:  # pragma: no cover
        logger.error(f"添加记忆失败: {exc}")
        return _format_command_error(str(exc))

    formatted = format_add_output(result)
    layer_label = layer_ids.get("layer") or target_layer or "unknown"
    return f"✅ 已添加至 {layer_label} 层：{formatted}"


@memory_command_entry.handle()
async def handle_memory_command(
    matcher: Matcher, event: MessageEvent, args: Message = CommandArg()
) -> None:
    text = args.extract_plain_text().strip()
    if not text:
        await finish_with(matcher, MEMORY_HELP_TEXT)
        return

    tokens = text.split()
    action = tokens[0].lower()
    positional, options = _split_tokens(tokens[1:])
    scope = _build_scope_from_event(event, options)

    # 临时调试：显示作用域信息
    if action == "debug":
        debug_info = (
            f"🔍 调试信息：\n"
            f"event.user_id = {getattr(event, 'user_id', None)}\n"
            f"event.group_id = {getattr(event, 'group_id', None)}\n"
            f"scope.user_id = {scope.user_id}\n"
            f"scope.agent_id = {scope.agent_id}\n"
            f"scope.run_id = {scope.run_id}\n"
            f"scope.has_scope() = {scope.has_scope()}\n"
            f"options = {options}"
        )
        await finish_with(matcher, debug_info)
        return

    if action in {"list", "ls"}:
        layer_arg = options.get("layer") or (positional[0] if positional else None)
        tags = _parse_tags(options.get("tags"))
        message_text = await _command_list_memory(
            scope, layers=_parse_layers(layer_arg), tags=tags
        )
        await finish_with(matcher, message_text)
        return

    if action in {"delete", "del", "rm"}:
        if not positional:
            await finish_with(
                matcher, _format_command_error("用法: mem delete <memory_id>")
            )
            return
        message_text = await _command_delete_memory(positional[0])
        await finish_with(matcher, message_text)
        return

    if action in {"clear", "delete_all", "purge"}:
        layer_arg = options.get("layer") or (positional[0] if positional else None)
        message_text = await _command_clear_memory(
            scope, layers=_parse_layers(layer_arg)
        )
        await finish_with(matcher, message_text)
        return

    if action in {"history", "hist"}:
        if not positional:
            await finish_with(
                matcher, _format_command_error("用法: mem history <memory_id>")
            )
            return
        message_text = await _command_history(positional[0])
        await finish_with(matcher, message_text)
        return

    if action in {"search", "s"}:
        if not positional:
            await finish_with(
                matcher, _format_command_error("用法: mem search <query> [layer=xxx]")
            )
            return
        query = " ".join(positional)
        layer_arg = options.get("layer")
        limit = (
            int(options.get("limit", "5"))
            if str(options.get("limit", "5")).isdigit()
            else 5
        )
        message_text = await _command_search(
            scope, query=query, layers=_parse_layers(layer_arg), limit=limit
        )
        await finish_with(matcher, message_text)
        return

    if action in {"add", "a"}:
        if not positional:
            await finish_with(
                matcher,
                _format_command_error("用法: mem add <文本> [layer=xxx] [tag=TYPE]"),
            )
            return
        memory_text = " ".join(positional)
        preferred_layer = options.get("layer") or options.get("scope")
        metadata = _parse_metadata(options)
        message_text = await _command_add(
            scope,
            memory_text=memory_text,
            preferred_layer=preferred_layer,
            metadata=metadata,
        )
        await finish_with(matcher, message_text)
        return

    await finish_with(matcher, MEMORY_HELP_TEXT)
