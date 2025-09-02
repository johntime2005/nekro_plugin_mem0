from typing import List, Dict, Any
from mem0 import Mem0
from loguru import logger

class MemoryPluginMethod:
    """
    封装了与 mem0 交互的具体方法，供 MemoryPlugin 调用。
    """
    def __init__(self, mem0_instance: Mem0):
        self.mem0 = mem0_instance

    def add(self, data: str, metadata: Dict[str, Any] = None) -> str:
        """
        调用 mem0 接口添加记忆。
        """
        try:
            self.mem0.add(data, metadata=metadata)
            logger.info(f"成功添加记忆: {data}")
            return f"记忆已添加: {data}"
        except Exception as e:
            logger.error(f"添加记忆失败: {e}")
            return f"添加记忆时出错: {e}"

    def get_all(self) -> List[Dict[str, Any]]:
        """
        调用 mem0 接口获取所有记忆。
        """
        try:
            memories = self.mem0.get_all()
            logger.info(f"成功获取 {len(memories)} 条记忆。")
            return memories
        except Exception as e:
            logger.error(f"获取所有记忆失败: {e}")
            return []

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        调用 mem0 接口搜索记忆。
        """
        try:
            results = self.mem0.search(query, limit=limit)
            logger.info(f"为查询 '{query}' 找到 {len(results)} 条相关记忆。")
            return results
        except Exception as e:
            logger.error(f"搜索记忆失败: {e}")
            return []

    def delete(self, memory_id: str) -> str:
        """
        调用 mem0 接口删除记忆。
        """
        try:
            self.mem0.delete(memory_id)
            logger.info(f"成功删除记忆 ID: {memory_id}")
            return f"记忆 ID {memory_id} 已被删除。"
        except Exception as e:
            logger.error(f"删除记忆 ID {memory_id} 失败: {e}")
            return f"删除记忆 ID {memory_id} 时出错: {e}"

    def get(self, memory_id: str) -> Dict[str, Any]:
        """
        调用 mem0 接口通过 ID 获取记忆。
        """
        try:
            memory = self.mem0.get(memory_id)
            if memory:
                logger.info(f"成功获取记忆 ID: {memory_id}")
                return memory
            else:
                logger.warning(f"未找到记忆 ID: {memory_id}")
                return {"error": f"未找到ID为 {memory_id} 的记忆"}
        except Exception as e:
            logger.error(f"获取记忆 ID {memory_id} 失败: {e}")
            return {"error": f"获取记忆 ID {memory_id} 时出错: {e}"}

