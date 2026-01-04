"""
插件方法
"""

from typing import Any, Dict, List, Optional, Set
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import logger
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
from .utils import resolve_memory_scope


def _memory_identifier(item: Dict[str, Any]) -> Optional[str]:
    """提取统一的记忆ID，便于跨层去重。"""
    for key in ("id", "memory_id"):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _build_layer_order(scope, layers: Optional[List[str]], preferred: Optional[str], session_enabled: bool) -> List[str]:
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
    if preferred:
        return [preferred]
    return scope.default_layer_order(enable_session_layer=session_enabled)


def _annotate_results(raw_results: Any, layer: str, seen_ids: Set[str]) -> List[Dict[str, Any]]:
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
    添加记忆。

    示例：
        await add_memory(_ctx, "喜欢科幻电影", user_id="user-1", metadata={"TYPE": "PREFERENCES"}, scope_level="persona")
    """
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法写入记忆"}

    target_layer = scope.pick_layer(preferred=scope_level, enable_session_layer=plugin_config.SESSION_ISOLATION)
    layer_ids = scope.layer_ids(target_layer or "")
    if layer_ids is None:
        return {"ok": False, "error": "未能确定可用的记忆层级，请提供 scope_level 或 user_id/agent_id/run_id"}

    result = client.add(
        memory,
        user_id=layer_ids["user_id"] if plugin_config.ENABLE_AGENT_SCOPE or target_layer == "global" else None,
        agent_id=layer_ids["agent_id"] if plugin_config.ENABLE_AGENT_SCOPE or target_layer == "persona" else None,
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
    按层级搜索记忆。

    示例：
        await search_memory(_ctx, "喜欢吃什么", user_id="user-1", layers=["conversation", "persona", "global"], limit=8)
    """
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少可用的 user_id/agent_id/run_id，无法搜索记忆"}

    layer_order = _build_layer_order(scope, layers=layers, preferred=scope_level, session_enabled=plugin_config.SESSION_ISOLATION)
    if not layer_order:
        return {"ok": False, "error": "未找到可搜索的层级"}

    merged_results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for layer in layer_order:
        layer_ids = scope.layer_ids(layer)
        if not layer_ids:
            continue
        search_run_id = layer_ids["run_id"] if plugin_config.SESSION_ISOLATION or layer_ids["layer"] == "conversation" else None
        search_agent_id = layer_ids["agent_id"] if plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "persona" else None
        search_user_id = layer_ids["user_id"] if layer_ids["layer"] == "global" else None

        raw_results = client.search(
            query,
            user_id=search_user_id,
            agent_id=search_agent_id,
            run_id=search_run_id,
            limit=limit,
            threshold=plugin_config.MEMORY_SEARCH_SCORE_THRESHOLD,
        )
        merged_results.extend(_annotate_results(raw_results, layer_ids["layer"], seen_ids))

    merged_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    merged_results = merged_results[:limit]

    formatted = format_search_output(merged_results, threshold=plugin_config.MEMORY_SEARCH_SCORE_THRESHOLD)
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
    获取指定层级的全部记忆。

    示例：
        await get_all_memory(_ctx, user_id="user-1", tags=["PREFERENCES"], layers=["persona", "global"])
    """
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法获取记忆"}

    layer_order = _build_layer_order(scope, layers=layers, preferred=scope_level, session_enabled=plugin_config.SESSION_ISOLATION)
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
            agent_id=layer_ids["agent_id"] if plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "persona" else None,
            run_id=layer_ids["run_id"] if layer_ids["layer"] == "conversation" else None,
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
    更新指定记忆内容。

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
    删除单条记忆。

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
    按层级批量删除记忆。

    示例：
        await delete_all_memory(_ctx, user_id="user-1", layers=["conversation", "persona"])
    """
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法删除记忆"}

    layer_order = _build_layer_order(scope, layers=layers, preferred=scope_level, session_enabled=plugin_config.SESSION_ISOLATION)
    if not layer_order:
        return {"ok": False, "error": "未找到可删除的层级"}

    deleted_layers: List[str] = []
    try:
        for layer in layer_order:
            layer_ids = scope.layer_ids(layer)
            if not layer_ids:
                continue
            client.delete_all(
                user_id=layer_ids["user_id"] if layer_ids["layer"] == "global" else None,
                agent_id=layer_ids["agent_id"] if plugin_config.ENABLE_AGENT_SCOPE or layer_ids["layer"] == "persona" else None,
                run_id=layer_ids["run_id"] if layer_ids["layer"] == "conversation" else None,
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
    查看记忆历史版本。

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
    return {"ok": True, "results": history_list, "text": format_history_text(history_list)}


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
            resp["text"] = resp.get("text") or _format_memory_list(resp.get("results", []))
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
    layer_order = scope.default_layer_order(enable_session_layer=config.SESSION_ISOLATION)
    available_layers = ", ".join(layer_order) if layer_order else "无可用层级"
    lines = [
        "你可以使用记忆插件在多个会话间维持用户/Agent的长期记忆。",
        "写入记忆：调用 add_memory(memory, user_id, agent_id?, run_id?, metadata?, scope_level?)，scope_level 可取 conversation/persona/global。",
        "检索记忆：调用 search_memory(query, user_id?, agent_id?, run_id?, scope_level?/layers?, limit?)，默认按层级顺序搜索。",
        "更新记忆：调用 update_memory(memory_id, new_memory)，用于修订已存知识。",
        "删除记忆：调用 delete_memory(memory_id) 删除单条，或 delete_all_memory(user_id?, agent_id?, run_id?) 清空作用域。",
        f"当前相似度阈值: {config.MEMORY_SEARCH_SCORE_THRESHOLD}。",
        f"可用层级顺序: {available_layers}。",
        "层级选择建议：对话上下文或短暂状态 -> conversation；与当前人设/角色绑定的习惯与设定 -> persona；与用户身份关联的长期资料 -> global。",
    ]

    if config.ENABLE_AGENT_SCOPE:
        lines.append("已启用 Agent/人设 级记忆：同一人设可在多会话间共享知识，不同人设彼此隔离。")
    else:
        lines.append("未启用 Agent 级记忆：记忆主要按用户/会话维度隔离。")

    if config.SESSION_ISOLATION:
        lines.append("已启用会话隔离：检索时优先限定 run_id（会话层），确保结果贴合当前对话。")
    else:
        lines.append("已关闭会话隔离：检索会聚合用户/Agent 级记忆，便于跨会话互通。")

    if scope.run_id:
        lines.append(f"对话层 run_id: {scope.run_id}")
    if scope.persona_id:
        lines.append(f"人设层 agent_id: {scope.persona_id}")
    if scope.user_id:
        lines.append(f"全局层 user_id: {scope.user_id}")

    lines.append("run_id 会被安全编码存储，可放心跨实例迁移。")
    return "\n".join(lines)
