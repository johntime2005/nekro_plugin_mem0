from typing import List, Dict, Any
from mem0 import Mem0
from loguru import logger
from .config import config as cfg
from .plugin_method import MemoryPluginMethod

class MemoryPlugin:
    """
    一个为 Nekro Agent 提供长期记忆能力的插件，基于 mem0 实现。
    它能让 Agent 记忆、检索和管理信息，并支持基于内容的智能搜索。
    """
    def __init__(self):
        """
        初始化记忆插件，加载 mem0 客户端。
        配置信息从 config.py 中读取，可以通过 .env 文件进行修改。
        """
        logger.info("正在初始化记忆插件...")
        try:
            # 初始化 mem0 客户端
            self.mem0 = Mem0(
                agent_id=cfg.mem0_agent_id,
                llm_config={
                    "model": cfg.mem0_llm_model,
                    "temperature": cfg.mem0_llm_temperature,
                },
                embed_config={
                    "model": cfg.mem0_embedding_model,
                },
                vector_store_config={
                    "provider": cfg.mem0_vector_store_provider,
                    "config": cfg.mem0_vector_store_config,
                },
            )
            self.methods = MemoryPluginMethod(self.mem0)
            logger.success("记忆插件初始化成功！")
        except Exception as e:
            logger.error(f"记忆插件初始化失败: {e}")
            raise

    def add_memory(self, data: str, metadata: Dict[str, Any] = None) -> str:
        """
        【核心功能】向记忆库中添加一条新的信息。

        当用户或系统需要记录关键信息以备将来使用时，调用此方法。
        例如：记录用户的偏好、一个重要的事实、或者一次对话的关键内容。

        Args:
            data (str): 需要记忆的核心信息内容。这应该是最关键的文本。
            metadata (Dict[str, Any], optional): 与该记忆相关的元数据，如来源、时间等。默认为 None。

        Returns:
            str: 记忆添加成功的确认信息。
        """
        return self.methods.add(data, metadata=metadata)

    def get_all_memories(self) -> List[Dict[str, Any]]:
        """
        【辅助功能】获取所有存储的记忆。

        用于调试或需要完整回顾所有记忆的场景。
        请注意：当记忆量很大时，这可能会返回大量数据。

        Returns:
            List[Dict[str, Any]]: 包含所有记忆的列表。
        """
        return self.methods.get_all()

    def search_memory(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        【核心功能】根据问题或关键词在记忆库中进行智能搜索。

        当需要根据用户的提问或某个主题，从过去的记忆中寻找相关信息时，调用此方法。
        这是实现长期记忆和上下文联想的关键。

        Args:
            query (str): 用于搜索的查询语句或关键词。
            limit (int, optional): 返回最相关记忆的最大数量。默认为 5。

        Returns:
            List[Dict[str, Any]]: 搜索到的相关记忆列表，按相关性排序。
        """
        return self.methods.search(query, limit=limit)


    def delete_memory(self, memory_id: str) -> str:
        """
        【管理功能】根据ID删除一条指定的记忆。

        用于修正错误的记忆或移除不再需要的信息。

        Args:
            memory_id (str): 要删除的记忆的唯一ID。

        Returns:
            str: 删除操作结果的确认信息。
        """
        return self.methods.delete(memory_id)

    def get_memory_by_id(self, memory_id: str) -> Dict[str, Any]:
        """
        【辅助功能】根据ID精确获取一条记忆。

        用于需要直接访问某条已知ID的记忆的场景。

        Args:
            memory_id (str): 要获取的记忆的唯一ID。

        Returns:
            Dict[str, Any]: 查找到的记忆详情。
        """
        return self.methods.get(memory_id)

