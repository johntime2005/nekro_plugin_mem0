from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional


class MemoryType(Enum):
    FACTS = "facts"
    PREFERENCES = "preferences"
    GOALS = "goals"
    TRAITS = "traits"
    RELATIONSHIPS = "relationships"
    EVENTS = "events"
    TOPICS = "topics"
    CONTEXTUAL = "contextual"
    TEMPORAL = "temporal"
    TASK = "task"
    SKILL = "skill"
    INTEREST = "interest"
    LOCATION = "location"


@dataclass
class EnhancedMemory:
    content: str
    type: MemoryType
    importance: int = 5
    expiration_date: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        self._validate_importance()
    
    def _validate_importance(self) -> None:
        if not 1 <= self.importance <= 10:
            raise ValueError(
                f"Importance must be between 1 and 10, got {self.importance}"
            )


# 记忆类型 → TTL 层级映射
_LONG_TERM_TYPES = {
    MemoryType.FACTS, MemoryType.PREFERENCES, MemoryType.GOALS,
    MemoryType.TRAITS, MemoryType.RELATIONSHIPS, MemoryType.SKILL,
    MemoryType.INTEREST,
}
_MEDIUM_TERM_TYPES = {
    MemoryType.CONTEXTUAL, MemoryType.TASK, MemoryType.LOCATION,
    MemoryType.TOPICS,
}
_SHORT_TERM_TYPES = {
    MemoryType.TEMPORAL, MemoryType.EVENTS,
}

# 类型字符串别名（处理单复数、同义词）
_TYPE_ALIASES = {
    "FACT": "FACTS", "FACTUAL": "FACTS",
    "PREFERENCE": "PREFERENCES",
    "GOAL": "GOALS",
    "TRAIT": "TRAITS",
    "RELATIONSHIP": "RELATIONSHIPS",
    "EVENT": "EVENTS",
    "TOPIC": "TOPICS",
    "PERSONAL": "TRAITS",
    "HABIT": "PREFERENCES",
}


def calculate_expiration_date(
    memory_type: MemoryType,
    importance: int = 5,
    now: Optional[datetime] = None,
) -> datetime:
    """根据记忆类型和重要性计算过期时间。

    长期类型（FACTS/PREFERENCES/GOALS/TRAITS/RELATIONSHIPS/SKILL/INTEREST）：30-365 天
    中期类型（CONTEXTUAL/TASK/LOCATION/TOPICS）：7-21 天
    短期类型（TEMPORAL/EVENTS）：0.5-2 天

    importance 1-10 在各层级内线性插值。
    """
    if now is None:
        now = datetime.now(timezone.utc)

    clamped = max(1, min(10, importance))
    ratio = (clamped - 1) / 9.0  # 0.0 ~ 1.0

    if memory_type in _LONG_TERM_TYPES:
        min_days, max_days = 30.0, 365.0
    elif memory_type in _MEDIUM_TERM_TYPES:
        min_days, max_days = 7.0, 21.0
    else:
        # 短期：12小时 ~ 48小时
        min_days, max_days = 0.5, 2.0

    ttl_days = min_days + ratio * (max_days - min_days)
    return now + timedelta(days=ttl_days)


def resolve_memory_type(type_str: str) -> MemoryType:
    """从字符串解析 MemoryType，不区分大小写，找不到则默认 CONTEXTUAL。"""
    normalized = type_str.strip().upper()
    normalized = _TYPE_ALIASES.get(normalized, normalized)
    try:
        return MemoryType(normalized.lower())
    except ValueError:
        return MemoryType.CONTEXTUAL