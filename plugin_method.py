"""
plugin_method.py - 记忆插件方法实现
参考 zxjwzn/nekro-plugin-memory 仓库实现
"""

import time
from typing import Any, Dict, List, Optional
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import config as core_config
from nekro_agent.core import logger
from nekro_agent.models.db_chat_channel import DBChatChannel
from nekro_agent.models.db_chat_message import DBChatMessage
from nekro_agent.schemas.chat_message import ChatMessage
from nekro_agent.schemas.signal import MsgSignal
from nekro_agent.services.plugin.base import SandboxMethodType
from .mem0_output_formatter import (
    format_add_output,
    format_get_all_output,
    format_history_output,
    format_search_output,
)
from .mem0_utils import get_mem0_client
from .plugin import PluginConfig, get_memory_config, plugin
from .utils import decode_id, get_preset_id

@plugin.mount_init_method()
async def init_plugin() -> None:
    """初始化插件"""
    logger.info("记忆插件初始化中...")

@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="添加记忆",
    description="为用户的个人资料添加一条新记忆，添加的记忆与该用户相关",
)
async def add_memory(
    _ctx: AgentCtx,
    memory: str,
    user_id: str,
    metadata: Dict[str, Any],
) -> None:
    """
    为用户的个人资料添加一条新记忆，添加的记忆与该用户相关。

    Args:
        memory (str): 要添加的记忆的文本内容。
        user_id (str): 关联的用户ID。代表添加的记忆内容与用户相关，这应该是用户的ID，而不是chat_key。
        metadata (Dict[str, Any]): 元数据标签。
        我们支持使用{TYPE: "TAGS"}来对不同类型的记忆进行标记
        目前可用的记忆类型标签包括：
            FACTS, PREFERENCES, GOALS, TRAITS, RELATIONSHIPS, EVENTS, TOPICS
        各个标签的具体作用请参考上文我们对这些标签的定义

    Returns:
        None.

    Examples:
        - add_memory("喜欢被叫做小明", "user_id", {TYPE: "FACTS"})
        - add_memory("喜欢在周末玩游戏", "user_id", {TYPE: "PREFERENCES"})
        - add_memory("下周四有会议", "user_id", {TYPE: "GOALS"})
        - add_memory("是个乐观友善的人", "user_id", {TYPE: "TRAITS"})
        - add_memory("和小王是同事", "user_id", {TYPE: "RELATIONSHIPS"})
        - add_memory("上个月参加了婚礼", "user_id", {TYPE: "EVENTS"})
        - add_memory("有提到对于人生的看法", "user_id", {TYPE: "TOPICS"})
    """
    mem0 = await get_mem0_client()
    plugin_config: PluginConfig = get_memory_config()
    if not mem0:
        logger.error("无法获取 mem0 客户端实例，无法添加记忆")
        return

    # 仅在有 chat_key 且启用隔离时设置 run_id
    run_id = None
    if plugin_config.SESSION_ISOLATION and _ctx.chat_key:
        run_id = str(_ctx.chat_key)

    # 不使用try except,出现问题直接报错
    res = await mem0.add(
        memory,
        user_id=user_id,
        agent_id=await get_preset_id(_ctx),
        run_id=run_id,
        metadata=metadata,
    )
    msg = format_add_output(res)
    logger.info(msg)

@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="搜索记忆",
    description="通过自然语言问句检索指定用户的相关记忆",
)
async def search_memory(
    _ctx: AgentCtx,
    query: str,
    user_id: str,
    tags: Optional[List[str]] = None,
) -> str:
    """
    通过自然语言问句检索指定用户的相关记忆。
    当上下文中没有出现所需要的相关记忆时，可以尝试使用此方法进行搜索

    Args:
        query (str): 查询语句，自然语言问题或关键词。
        user_id (str): 关联的用户ID。代表查询的记忆与该用户相关，这应该是用户的ID，而不是chat_key。
        tags (Optional[List[str]]): 可选的记忆类型标签过滤列表。
        目前可用的记忆类型标签包括：
            FACTS, PREFERENCES, GOALS, TRAITS, RELATIONSHIPS, EVENTS, TOPICS
        各个标签的具体作用请参考上文我们对这些标签的定义

    Returns:
        str: 结构化的搜索结果文本，适合直接展示；失败时返回错误信息。

    Examples:
        search_memory("他喜欢吃什么？", "17295800")
        search_memory("上周讨论的话题", "73235808", ["TOPICS"])
        search_memory("他的个人喜好", "12345", ["PREFERENCES", "TRAITS"])
    """
    mem0 = await get_mem0_client()
    plugin_config: PluginConfig = get_memory_config()
    if not mem0:
        return "无法获取 mem0 客户端实例"

    # 仅在有 chat_key 且启用隔离时设置 run_id
    run_id = None
    if plugin_config.SESSION_ISOLATION and _ctx.chat_key:
        run_id = str(_ctx.chat_key)

    try:
        res = await mem0.search(
            query,
            user_id=user_id,
            agent_id=await get_preset_id(_ctx),
            run_id=run_id,
            tags=tags,
        )
        msg = format_search_output(res)
        logger.info(f"搜索记忆成功: {query}")
        return msg
    except Exception as e:
        logger.error(f"搜索记忆失败: {e}")
        return f"搜索记忆时出错: {e}"

@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="获取所有记忆",
    description="获取指定用户的所有记忆，支持按标签过滤",
)
async def get_all_memory(
    _ctx: AgentCtx,
    user_id: str,
    tags: Optional[List[str]] = None,
) -> str:
    """
    获取指定用户的全部记忆条目。

    Args:
        user_id (str): 关联的用户ID。代表获取的记忆与该用户相关，这应该是用户的ID，而不是chat_key。
        tags (Optional[List[str]]): 可选的记忆类型标签过滤列表。
        目前可用的记忆类型标签包括：
            FACTS, PREFERENCES, GOALS, TRAITS, RELATIONSHIPS, EVENTS, TOPICS
        各个标签的具体作用请参考上文我们对这些标签的定义

    Returns:
        str: 结构化的记忆列表文本；失败时返回空字符串。

    Examples:
        get_all_memory("17295800")
        get_all_memory("", ["PREFERENCES"])
        get_all_memory("12345", ["FACTS", "RELATIONSHIPS"])
    """
    mem0 = await get_mem0_client()
    plugin_config: PluginConfig = get_memory_config()
    if not mem0:
        return "无法获取 mem0 客户端实例"

    # 仅在有 chat_key 且启用隔离时设置 run_id
    run_id = None
    if plugin_config.SESSION_ISOLATION and _ctx.chat_key:
        run_id = str(_ctx.chat_key)

    try:
        res = await mem0.get_all(
            user_id=user_id,
            agent_id=await get_preset_id(_ctx),
            run_id=run_id,
            tags=tags,
        )
        msg = format_get_all_output(res)
        logger.info(f"获取所有记忆成功: {user_id}")
        return msg
    except Exception as e:
        logger.error(f"获取所有记忆失败: {e}")
        return f"获取所有记忆时出错: {e}"

@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="删除所有记忆",
    description="删除指定用户的所有记忆",
)
async def delete_all_memory(_ctx: AgentCtx, user_id: str) -> None:
    """
    删除指定用户的所有记忆。

    Args:
        user_id (str): 关联的用户ID。代表要删除的记忆与该用户相关，这应该是用户的ID，而不是chat_key。

    Returns:
        None.

    Example:
        delete_all_memory("17295800")
        delete_all_memory("")
    """
    mem0 = await get_mem0_client()
    plugin_config: PluginConfig = get_memory_config()
    if not mem0:
        return

    # 仅在有 chat_key 且启用隔离时设置 run_id
    run_id = None
    if plugin_config.SESSION_ISOLATION and _ctx.chat_key:
        run_id = str(_ctx.chat_key)

    await mem0.delete_all(
        user_id=user_id,
        agent_id=await get_preset_id(_ctx),
        run_id=run_id,
    )
    logger.info(f"删除所有记忆成功: {user_id}")

@plugin.mount_cleanup_method()
async def clean_up() -> None:
    """清理插件"""
    logger.info("记忆插件资源已清理。")

