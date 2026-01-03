"""
辅助函数
"""

import base64
from dataclasses import dataclass
from typing import Optional

from nekro_agent.api.schemas import AgentCtx


def get_preset_id(chat_key: Optional[str]) -> str:
    if not chat_key:
        return "default"
    return base64.urlsafe_b64encode(chat_key.encode()).decode()


def decode_id(encoded: str) -> str:
    return base64.urlsafe_b64decode(encoded.encode()).decode()


def _normalize(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


@dataclass
class MemoryScope:
    user_id: Optional[str]
    agent_id: Optional[str]
    run_id: Optional[str]

    def has_scope(self) -> bool:
        return any([self.user_id, self.agent_id, self.run_id])


def resolve_memory_scope(
    ctx: AgentCtx,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> MemoryScope:
    resolved_user_id = _normalize(user_id) or _normalize(getattr(ctx, "user_id", None))
    resolved_agent_id = _normalize(agent_id) or _normalize(getattr(ctx, "agent_id", None) or getattr(ctx, "bot_id", None))
    resolved_run_id = _normalize(run_id) or _normalize(getattr(ctx, "chat_key", None) or getattr(ctx, "session_id", None))

    if resolved_run_id:
        resolved_run_id = get_preset_id(resolved_run_id)

    return MemoryScope(user_id=resolved_user_id, agent_id=resolved_agent_id, run_id=resolved_run_id)
