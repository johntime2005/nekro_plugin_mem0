"""
utils.py - 通用工具函数
"""

import hashlib
from typing import Optional
from nekro_agent.api.schemas import AgentCtx


async def get_preset_id(_ctx: AgentCtx) -> str:
    """
    获取预设ID，用于隔离不同Agent的记忆
    """
    # 使用session_id作为agent_id的基础
    if hasattr(_ctx, 'session') and _ctx.session:
        session_id = _ctx.session.session_id
        # 创建一个简短的哈希作为agent_id
        return hashlib.md5(session_id.encode()).hexdigest()[:8]
    return "default"


def decode_id(encoded_id: str) -> str:
    """
    解码ID（如果需要的话）
    """
    return encoded_id
