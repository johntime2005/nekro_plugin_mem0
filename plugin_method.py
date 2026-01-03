"""
插件方法
"""

from typing import Any, Dict, List, Optional
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import logger
from nekro_agent.services.plugin.base import SandboxMethodType
from .mem0_output_formatter import format_add_output, format_search_output
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
) -> List[Dict[str, Any]]:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return []

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return []

    search_run_id = scope.run_id if plugin_config.SESSION_ISOLATION or not (scope.user_id or scope.agent_id) else None
    search_agent_id = scope.agent_id if plugin_config.ENABLE_AGENT_SCOPE else None

    if not any([scope.user_id, search_agent_id, search_run_id]):
        return []

    results = client.search(
        query,
        user_id=scope.user_id,
        agent_id=search_agent_id,
        run_id=search_run_id,
        limit=limit,
        threshold=plugin_config.MEMORY_SEARCH_SCORE_THRESHOLD,
    )
    return format_search_output(results)
