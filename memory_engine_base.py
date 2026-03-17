from abc import ABC, abstractmethod

_ENGINE_REGISTRY: dict[str, type] = {}


def register_engine(name: str):
    def decorator(cls: type) -> type:
        _ENGINE_REGISTRY[name] = cls
        return cls
    return decorator


def get_engine(name: str) -> type:
    if name not in _ENGINE_REGISTRY:
        raise ValueError(f"Engine '{name}' not found. Available: {list(_ENGINE_REGISTRY.keys())}")
    return _ENGINE_REGISTRY[name]


class MemoryEngineBase(ABC):
    
    @abstractmethod
    def add_memory(self, key: str, value: object) -> None:
        pass
    
    @abstractmethod
    def search_memory(self, query: str, **kwargs) -> list[dict[str, object]]:
        pass
    
    @abstractmethod
    def remove_memory(self, key: str) -> bool:
        pass
