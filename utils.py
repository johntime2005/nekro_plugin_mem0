"""
辅助函数
"""

import base64
from dataclasses import dataclass
from typing import List, Optional

from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import logger
from nekro_agent.core.config import ModelConfigGroup, config as core_config


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
    preset_title: Optional[str] = None

    def has_scope(self) -> bool:
        return any([self.user_id, self.agent_id, self.run_id])

    @property
    def persona_id(self) -> Optional[str]:
        """别名：agent_id 即人设ID。"""
        return self.agent_id

    def available_layers(self) -> dict:
        return {
            "conversation": bool(self.run_id),
            "persona": bool(self.agent_id),
            "global": bool(self.user_id),
        }

    def _normalize_layer(self, layer: str) -> Optional[str]:
        mapping = {
            "conversation": "conversation",
            "session": "conversation",
            "run": "conversation",
            "persona": "persona",
            "preset": "persona",
            "agent": "persona",
            "global": "global",
            "user": "global",
        }
        return mapping.get((layer or "").lower())

    def layer_ids(self, layer: str) -> Optional[dict]:
        normalized = self._normalize_layer(layer)
        if normalized == "conversation" and self.run_id:
            return {"layer": "conversation", "user_id": None, "agent_id": None, "run_id": self.run_id}
        if normalized == "persona" and self.agent_id:
            return {"layer": "persona", "user_id": None, "agent_id": self.agent_id, "run_id": None}
        if normalized == "global" and self.user_id:
            return {"layer": "global", "user_id": self.user_id, "agent_id": None, "run_id": None}
        return None

    def default_layer_order(self, enable_session_layer: bool = True) -> List[str]:
        order: List[str] = []
        if enable_session_layer and self.run_id:
            order.append("conversation")
        if self.agent_id:
            order.append("persona")
        if self.user_id:
            order.append("global")
        if not order and self.run_id:
            # 即便关闭会话隔离，仍可在缺省场景下回退到对话层，避免无层级可用
            order.append("conversation")
        return order

    def pick_layer(self, preferred: Optional[str], enable_session_layer: bool = True) -> Optional[str]:
        """选择最合适的层级，优先使用显式指定，其次按默认优先级。"""
        if preferred:
            normalized = self._normalize_layer(preferred)
            if normalized and self.layer_ids(normalized):
                return normalized
        for layer in self.default_layer_order(enable_session_layer=enable_session_layer):
            if self.layer_ids(layer):
                return layer
        return None


def resolve_memory_scope(
    ctx: AgentCtx,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    persona_id: Optional[str] = None,
) -> MemoryScope:
    def _safe_getattr(obj, name: str, default=None) -> Optional[str]:
        try:
            return getattr(obj, name, default)
        except Exception:
            return default

    # 调试日志：记录 AgentCtx 的原始信息
    db_user = _safe_getattr(ctx, "db_user")
    db_chat_channel = _safe_getattr(ctx, "db_chat_channel")
    logger.debug(
        f"[Memory] resolve_memory_scope - "
        f"ctx.user_id={_safe_getattr(ctx, 'user_id')}, "
        f"ctx.agent_id={_safe_getattr(ctx, 'agent_id')}, "
        f"ctx.bot_id={_safe_getattr(ctx, 'bot_id')}, "
        f"ctx.chat_key={_safe_getattr(ctx, 'chat_key')}, "
        f"ctx.session_id={_safe_getattr(ctx, 'session_id')}, "
        f"db_user.unique_id={_safe_getattr(db_user, 'unique_id') if db_user else None}, "
        f"db_chat_channel.preset_id={_safe_getattr(db_chat_channel, 'preset_id') if db_chat_channel else None}, "
        f"db_chat_channel.channel_name={_safe_getattr(db_chat_channel, 'channel_name') if db_chat_channel else None}"
    )

    resolved_user_id = _normalize(user_id)
    if not resolved_user_id:
        user_unique_id = _safe_getattr(db_user, "unique_id") if db_user else None
        resolved_user_id = (
            _normalize(user_unique_id)
            or _normalize(_safe_getattr(ctx, "user_id", None))
            or _normalize(_safe_getattr(ctx, "channel_id", None))
        )

    resolved_agent_id = _normalize(agent_id) or _normalize(persona_id) or _normalize(_safe_getattr(ctx, "agent_id", None) or _safe_getattr(ctx, "bot_id", None))
    preset_title = None
    if not resolved_agent_id:
        preset_id = _safe_getattr(db_chat_channel, "preset_id") if db_chat_channel else None
        if preset_id is not None:
            resolved_agent_id = f"preset:{preset_id}"
        elif db_chat_channel is not None:
            resolved_agent_id = "preset:default"
        preset_title = _safe_getattr(db_chat_channel, "channel_name") if db_chat_channel else None

    resolved_run_source = _normalize(run_id) or _normalize(_safe_getattr(ctx, "chat_key", None) or _safe_getattr(ctx, "session_id", None))
    resolved_run_id = get_preset_id(resolved_run_source) if resolved_run_source else None

    # 调试日志：记录解析结果
    logger.info(
        f"[Memory] resolve_memory_scope 结果 - "
        f"user_id={resolved_user_id}, agent_id={resolved_agent_id}, "
        f"run_id={resolved_run_id}, preset_title={preset_title}"
    )

    return MemoryScope(user_id=resolved_user_id, agent_id=resolved_agent_id, run_id=resolved_run_id, preset_title=preset_title)


def get_model_group_info(model_name: str, expected_type: Optional[str] = None) -> ModelConfigGroup:
    """根据模型组名称获取配置，必要时校验模型类型。"""
    try:
        group = core_config.MODEL_GROUPS[model_name]
    except KeyError as exc:
        raise ValueError(f"模型组 '{model_name}' 不存在，请确认配置正确") from exc

    if expected_type and group.MODEL_TYPE != expected_type:
        logger.warning(f"模型组 '{model_name}' 类型为 '{group.MODEL_TYPE}'，与期望的 '{expected_type}' 不一致")
    return group
