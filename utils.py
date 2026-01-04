"""
辅助函数
"""

import base64
from dataclasses import dataclass
from typing import Optional

from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import logger
from nekro_agent.core.config import ModelConfigGroup, config as core_config


def _encode_scope_id(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return base64.urlsafe_b64encode(str(raw).encode()).decode()


def get_preset_id(scope_key: Optional[str]) -> str:
    """兼容旧方法：对任意字符串做url-safe编码，用于run_id等场景。"""
    encoded = _encode_scope_id(scope_key)
    return encoded or "default"


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
    persona_id: Optional[str]
    run_id: Optional[str]

    def has_scope(self) -> bool:
        return any([self.user_id, self.persona_id, self.run_id])


def resolve_memory_scope(
    ctx: AgentCtx,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> MemoryScope:
    """分三层：会话(run)、人设(preset/agent)、全局(user)。"""
    resolved_user_id = _normalize(user_id) or _normalize(getattr(ctx, "user_id", None))
    resolved_persona_id = _normalize(agent_id) or _normalize(
        getattr(ctx, "preset_id", None)  # 人设层
        or getattr(ctx, "persona_id", None)
        or getattr(ctx, "agent_id", None)
        or getattr(ctx, "bot_id", None)
    )
    resolved_run_id = _normalize(run_id) or _normalize(getattr(ctx, "chat_key", None) or getattr(ctx, "session_id", None))

    if resolved_run_id:
        resolved_run_id = get_preset_id(resolved_run_id)

    return MemoryScope(user_id=resolved_user_id, persona_id=resolved_persona_id, run_id=resolved_run_id)


def get_model_group_info(model_name: str, expected_type: Optional[str] = None) -> ModelConfigGroup:
    """根据模型组名称获取配置，必要时校验模型类型。"""
    try:
        group = core_config.MODEL_GROUPS[model_name]
    except KeyError as exc:
        raise ValueError(f"模型组 '{model_name}' 不存在，请确认配置正确") from exc

    if expected_type and group.MODEL_TYPE != expected_type:
        logger.warning(f"模型组 '{model_name}' 类型为 '{group.MODEL_TYPE}'，与期望的 '{expected_type}' 不一致")
    return group
