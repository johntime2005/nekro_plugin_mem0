"""Basic 引擎：包装 mem0 向量搜索"""
from typing import Any

from .memory_engine_base import MemoryEngineBase, register_engine
from .mem0_utils import get_mem0_client


@register_engine("basic")
class BasicEngine(MemoryEngineBase):
    """Basic 引擎：直接使用 mem0 的向量搜索（默认引擎）"""
    
    def __init__(self, config: Any) -> None:
        self.config: Any = config
        self.client: Any = None
    
    async def initialize(self):
        """初始化 mem0 客户端"""
        self.client = await get_mem0_client()
    
    def add_memory(self, key: str, value: object) -> None:
        """添加记忆（委托给 mem0）"""
        if not self.client:
            return
        self.client.add(value, user_id=key)
    
    def search_memory(self, query: str, **kwargs) -> list[dict[str, object]]:
        """搜索记忆（委托给 mem0）"""
        if not self.client:
            return []
        results = self.client.search(query, **kwargs)
        return results if results else []
    
    def remove_memory(self, key: str) -> bool:
        """删除记忆（委托给 mem0）"""
        if not self.client:
            return False
        try:
            self.client.delete(key)
            return True
        except Exception:
            return False
