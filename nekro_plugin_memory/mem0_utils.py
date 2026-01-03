"""
mem0 工具
"""

import os
from urllib.parse import urlparse
from typing import Optional, Union

from mem0 import Memory, MemoryClient
from mem0.configs.base import MemoryConfig
from mem0.embeddings.configs import EmbedderConfig
from mem0.llms.configs import LlmConfig
from mem0.vector_stores.configs import VectorStoreConfig
from nekro_agent.core import logger
from .plugin import get_memory_config, PluginConfig

_mem0_instance: Optional[Union[Memory, MemoryClient]] = None
_last_config_hash: Optional[str] = None


async def get_mem0_client() -> Optional[Union[Memory, MemoryClient]]:
    global _mem0_instance, _last_config_hash

    plugin_config: PluginConfig = get_memory_config()
    current_config_hash = str(hash((
        plugin_config.OPENAI_API_KEY,
        plugin_config.MEM0_API_KEY,
        plugin_config.MEM0_BASE_URL,
        plugin_config.VECTOR_DB,
        plugin_config.QDRANT_URL,
        plugin_config.QDRANT_API_KEY,
        plugin_config.REDIS_URL,
        plugin_config.COLLECTION_NAME,
        plugin_config.EMBEDDING_MODEL,
        plugin_config.EMBEDDING_DIMS,
        plugin_config.LLM_MODEL,
        plugin_config.ENABLE_AGENT_SCOPE,
    )))

    if _last_config_hash != current_config_hash or _mem0_instance is None:
        try:
            logger.info("正在创建新的mem0客户端实例...")

            if plugin_config.OPENAI_API_KEY:
                os.environ["OPENAI_API_KEY"] = plugin_config.OPENAI_API_KEY

            if plugin_config.MEM0_API_KEY:
                _mem0_instance = MemoryClient(
                    api_key=plugin_config.MEM0_API_KEY,
                    host=plugin_config.MEM0_BASE_URL or None,
                )
            else:
                vector_config: dict = {}
                if plugin_config.VECTOR_DB == "qdrant":
                    parsed_url = urlparse(plugin_config.QDRANT_URL)
                    vector_config = {
                        "collection_name": plugin_config.COLLECTION_NAME,
                        "embedding_model_dims": plugin_config.EMBEDDING_DIMS,
                    }
                    if plugin_config.QDRANT_API_KEY:
                        vector_config.update({"url": plugin_config.QDRANT_URL, "api_key": plugin_config.QDRANT_API_KEY})
                    elif parsed_url.scheme:
                        vector_config.update(
                            {
                                "host": parsed_url.hostname or "localhost",
                                "port": parsed_url.port or 6333,
                            }
                        )
                    else:
                        vector_config.update({"path": plugin_config.QDRANT_URL})
                elif plugin_config.VECTOR_DB == "chroma":
                    vector_config = {
                        "path": plugin_config.CHROMA_PATH,
                        "collection_name": plugin_config.COLLECTION_NAME,
                    }
                elif plugin_config.VECTOR_DB == "redis":
                    vector_config = {
                        "redis_url": plugin_config.REDIS_URL,
                        "collection_name": plugin_config.COLLECTION_NAME,
                        "embedding_model_dims": plugin_config.EMBEDDING_DIMS,
                    }
                else:
                    raise ValueError(f"暂不支持的向量数据库类型: {plugin_config.VECTOR_DB}")

                embedder = EmbedderConfig(
                    provider="openai",
                    config={
                        "model": plugin_config.EMBEDDING_MODEL,
                        "embedding_dims": plugin_config.EMBEDDING_DIMS,
                        "api_key": plugin_config.OPENAI_API_KEY,
                    },
                )
                llm = LlmConfig(provider="openai", config={"model": plugin_config.LLM_MODEL, "api_key": plugin_config.OPENAI_API_KEY})
                vector_store = VectorStoreConfig(provider=plugin_config.VECTOR_DB, config=vector_config)

                memory_config = MemoryConfig(embedder=embedder, vector_store=vector_store, llm=llm)
                _mem0_instance = Memory(config=memory_config)

            _last_config_hash = current_config_hash
            logger.success("mem0客户端实例创建成功")
        except Exception as e:
            logger.error(f"创建mem0客户端实例失败: {e}")
            _mem0_instance = None

    return _mem0_instance
