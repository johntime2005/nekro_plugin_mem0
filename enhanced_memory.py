from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


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