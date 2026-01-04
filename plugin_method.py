"""
插件方法
"""

from typing import Any, Dict, List, Optional
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import logger
from nekro_agent.services.plugin.base import SandboxMethodType
from .mem0_output_formatter import (
    format_add_output,
    format_get_all_output,
    format_history_output,
    format_history_text,
    format_search_output,
)
from .mem0_utils import get_mem0_client
from .plugin import get_memory_config, plugin
from .utils import resolve_memory_scope


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
) -> Dict[str, Any]:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法写入记忆"}

    result = client.add(
        memory,
        user_id=scope.user_id,
        agent_id=scope.agent_id if plugin_config.ENABLE_AGENT_SCOPE else None,
        run_id=scope.run_id,
        metadata=metadata or {},
    )
    return format_add_output(result)


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
    limit: int = 5,
) -> Dict[str, Any]:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法搜索记忆"}

    search_run_id = scope.run_id if plugin_config.SESSION_ISOLATION or not (scope.user_id or scope.agent_id) else None
    search_agent_id = scope.agent_id if plugin_config.ENABLE_AGENT_SCOPE else None

    if not any([scope.user_id, search_agent_id, search_run_id]):
        return {"ok": False, "error": "缺少可用的 user_id/agent_id/run_id"}

    raw_results = client.search(
        query,
        user_id=scope.user_id,
        agent_id=search_agent_id,
        run_id=search_run_id,
        limit=limit,
        threshold=plugin_config.MEMORY_SEARCH_SCORE_THRESHOLD,
    )
    formatted = format_search_output(raw_results, threshold=plugin_config.MEMORY_SEARCH_SCORE_THRESHOLD)
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
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法获取记忆"}

    results = client.get_all(
        user_id=scope.user_id,
        agent_id=scope.agent_id if plugin_config.ENABLE_AGENT_SCOPE else None,
        run_id=scope.run_id if plugin_config.SESSION_ISOLATION else None,
    )
    formatted = format_get_all_output(results, tags=tags)
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
) -> Dict[str, Any]:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法删除记忆"}

    try:
        client.delete_all(
            user_id=scope.user_id,
            agent_id=scope.agent_id if plugin_config.ENABLE_AGENT_SCOPE else None,
            run_id=scope.run_id if plugin_config.SESSION_ISOLATION else None,
        )
    except Exception as exc:  # pragma: no cover
        logger.error(f"删除全部记忆失败: {exc}")
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "message": "已删除指定作用域记忆"}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="获取记忆历史",
    description="查看指定记忆的历史版本",
)
async def get_memory_history(
    _ctx: AgentCtx,
    memory_id: str,
) -> Dict[str, Any]:
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


@plugin.mount_prompt_inject_method(
    name="memory_layer_hint",
    description="为LLM注入可用的长期记忆能力提示，包含跨用户/Agent/会话的存取方式",
)
async def inject_memory_prompt(_ctx: AgentCtx) -> str:
    config = get_memory_config()
    lines = [
        "你可以使用记忆插件在多个会话间维持用户/Agent的长期记忆。",
        "写入记忆：调用 add_memory(memory, user_id, agent_id?, run_id?, metadata?)。metadata 可带标签帮助分类。",
        "检索记忆：调用 search_memory(query, user_id?, agent_id?, run_id?, limit?)，默认会结合会话隔离与相似度阈值。",
        "更新记忆：调用 update_memory(memory_id, new_memory)，用于修订已存知识。",
        "删除记忆：调用 delete_memory(memory_id) 删除单条，或 delete_all_memory(user_id?, agent_id?, run_id?) 清空作用域。",
        f"当前相似度阈值: {config.MEMORY_SEARCH_SCORE_THRESHOLD}。",
    ]

    if config.ENABLE_AGENT_SCOPE:
        lines.append("已启用 Agent 级记忆：同一 Agent 可在多会话间共享知识。")
    else:
        lines.append("未启用 Agent 级记忆：记忆主要按用户/会话维度隔离。")

    if config.SESSION_ISOLATION:
        lines.append("已启用会话隔离：检索时优先限定 run_id（会话层），确保结果贴合当前对话。")
    else:
        lines.append("已关闭会话隔离：检索会聚合用户/Agent 级记忆，便于跨会话互通。")

    lines.append("run_id 会被安全编码存储，可放心跨实例迁移。")
    return "\n".join(lines)
