"""
插件方法
"""

from typing import Any, Dict, List
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import logger
from nekro_agent.services.plugin.base import SandboxMethodType
from .mem0_utils import get_mem0_client
from .plugin import plugin


@plugin.mount_init_method()
async def init_plugin() -> None:
    logger.info("记忆插件初始化中...")


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="添加记忆",
    description="为用户的个人资料添加一条新记忆，添加的记忆与该用户相关",
)
async def add_memory(_ctx: AgentCtx, memory: str, user_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}
    result = client.add(memory, user_id=user_id, metadata=metadata)
    return result


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="搜索记忆",
    description="根据查询语句搜索用户记忆",
)
async def search_memory(_ctx: AgentCtx, query: str, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    client = await get_mem0_client()
    if client is None:
        return []
    results = client.search(query, user_id=user_id, limit=limit)
    return results
