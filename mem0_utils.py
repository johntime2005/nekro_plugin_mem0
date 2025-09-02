"""
mem0 工具
"""

from typing import Optional
from mem0 import Memory
from nekro_agent.core import logger
from .plugin import get_memory_config, PluginConfig

_mem0_instance: Optional[Memory] = None
_last_config_hash: Optional[str] = None


async def get_mem0_client() -> Optional[Memory]:
    global _mem0_instance, _last_config_hash

    plugin_config: PluginConfig = get_memory_config()
    current_config_hash = str(hash((
        plugin_config.OPENAI_API_KEY,
        plugin_config.MEM0_API_KEY,
        plugin_config.MEM0_BASE_URL,
        plugin_config.VECTOR_DB,
        plugin_config.QDRANT_URL,
        plugin_config.QDRANT_API_KEY,
        plugin_config.EMBEDDING_MODEL,
        plugin_config.EMBEDDING_DIMS,
    )))

    if _last_config_hash != current_config_hash or _mem0_instance is None:
        try:
            logger.info("正在创建新的mem0客户端实例...")

            vector_config = {}
            if plugin_config.VECTOR_DB == "qdrant":
                vector_config = {"url": plugin_config.QDRANT_URL, "api_key": plugin_config.QDRANT_API_KEY}
            elif plugin_config.VECTOR_DB == "chroma":
                vector_config = {"path": plugin_config.CHROMA_PATH}

            _mem0_instance = Memory(
                api_key=plugin_config.MEM0_API_KEY,
                embed_config={"model": plugin_config.EMBEDDING_MODEL, "dims": plugin_config.EMBEDDING_DIMS},
                vector_store_config={"provider": plugin_config.VECTOR_DB, "config": vector_config},
            )
            _last_config_hash = current_config_hash
            logger.success("mem0客户端实例创建成功")
        except Exception as e:
            logger.error(f"创建mem0客户端实例失败: {e}")
            _mem0_instance = None

    return _mem0_instance
