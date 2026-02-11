"""
mem0 工具
"""

from typing import Optional, Union
from urllib.parse import urlparse

from mem0 import Memory, MemoryClient
from mem0.configs.base import MemoryConfig
from mem0.embeddings.configs import EmbedderConfig
from mem0.llms.configs import LlmConfig
from mem0.vector_stores.configs import VectorStoreConfig
from nekro_agent.api.core import get_qdrant_config, get_qdrant_client, logger
from .plugin import PluginConfig, get_memory_config, plugin
from .utils import get_model_group_info

_mem0_instance: Optional[Union[Memory, MemoryClient]] = None
_last_config_hash: Optional[str] = None


def _config_incomplete(plugin_config: PluginConfig) -> bool:
    if plugin_config.MEM0_API_KEY:
        return False

    try:
        llm_group = get_model_group_info(
            plugin_config.MEMORY_MANAGE_MODEL, expected_type="chat"
        )
        embedding_group = get_model_group_info(
            plugin_config.TEXT_EMBEDDING_MODEL, expected_type="embedding"
        )
    except ValueError as exc:
        logger.error(str(exc))
        return True

    # 验证模型组类型是否正确
    if llm_group.MODEL_TYPE != "chat":
        logger.error(
            f"记忆管理模型组 '{plugin_config.MEMORY_MANAGE_MODEL}' 类型为 '{llm_group.MODEL_TYPE}'，必须是 'chat' 类型"
        )
        return True
    if embedding_group.MODEL_TYPE != "embedding":
        logger.error(
            f"向量嵌入模型组 '{plugin_config.TEXT_EMBEDDING_MODEL}' 类型为 '{embedding_group.MODEL_TYPE}'，必须是 'embedding' 类型"
        )
        return True

    def _missing(value: Optional[str]) -> bool:
        return value is None or str(value).strip() == ""

    return any(
        [
            _missing(llm_group.API_KEY),
            _missing(llm_group.CHAT_MODEL),
            _missing(embedding_group.API_KEY),
            _missing(embedding_group.CHAT_MODEL),
        ]
    )


def _build_config_hash(
    plugin_config: PluginConfig,
    llm_group,
    embedding_group,
    qdrant_config,
) -> str:
    # 集合名称由 plugin.get_vector_collection_name() 生成，不依赖配置
    parts = [
        plugin_config.MEM0_API_KEY or "",
        plugin_config.MEM0_BASE_URL or "",
        plugin_config.VECTOR_DB,
        plugin_config.QDRANT_URL or "",
        plugin_config.QDRANT_API_KEY or "",
        qdrant_config.url or "",
        qdrant_config.api_key or "",
        plugin_config.REDIS_URL,
        plugin_config.CHROMA_PATH,
        str(plugin_config.EMBEDDING_DIMS),
        plugin_config.MEMORY_MANAGE_MODEL,
        plugin_config.TEXT_EMBEDDING_MODEL,
    ]

    if llm_group:
        parts.extend(
            [
                llm_group.API_KEY or "",
                llm_group.CHAT_MODEL or "",
                llm_group.BASE_URL or "",
            ]
        )
    if embedding_group:
        parts.extend(
            [
                embedding_group.API_KEY or "",
                embedding_group.CHAT_MODEL or "",
                embedding_group.BASE_URL or "",
            ]
        )

    return str(hash("|".join(parts)))


async def get_mem0_client() -> Optional[Union[Memory, MemoryClient]]:
    global _mem0_instance, _last_config_hash

    plugin_config: PluginConfig = get_memory_config()
    qdrant_config = get_qdrant_config()

    if _config_incomplete(plugin_config):
        logger.warning(
            "❌ 记忆模块配置不完整或类型错误：请在插件配置中正确设置 记忆管理模型（chat类型）和 向量嵌入模型（embedding类型）。"
        )
        return None

    llm_group = None
    embedding_group = None
    if not plugin_config.MEM0_API_KEY:
        try:
            logger.debug(
                f"正在加载模型配置: MEMORY_MANAGE_MODEL={plugin_config.MEMORY_MANAGE_MODEL}, TEXT_EMBEDDING_MODEL={plugin_config.TEXT_EMBEDDING_MODEL}"
            )
            llm_group = get_model_group_info(
                plugin_config.MEMORY_MANAGE_MODEL, expected_type="chat"
            )
            embedding_group = get_model_group_info(
                plugin_config.TEXT_EMBEDDING_MODEL, expected_type="embedding"
            )
            logger.debug(f"✓ 模型配置加载成功")
        except ValueError as exc:
            logger.error(f"❌ 模型配置加载失败: {exc}")
            return None

    current_config_hash = _build_config_hash(
        plugin_config, llm_group, embedding_group, qdrant_config
    )

    if _last_config_hash != current_config_hash or _mem0_instance is None:
        try:
            import mem0

            logger.info(
                f"🚀 [Mem0 Plugin v1.4.0] 初始化中... (mem0ai lib: {getattr(mem0, '__version__', 'unknown')})"
            )
            logger.info("正在创建新的mem0客户端实例...")

            if plugin_config.MEM0_API_KEY:
                _mem0_instance = MemoryClient(
                    api_key=plugin_config.MEM0_API_KEY,
                    host=plugin_config.MEM0_BASE_URL or None,
                )
            else:
                vector_config: dict = {}
                if plugin_config.VECTOR_DB == "qdrant":
                    # 使用插件专属的集合名称，确保隔离性
                    collection_name = plugin.get_vector_collection_name()
                    vector_config = {
                        "collection_name": collection_name,
                        "embedding_model_dims": plugin_config.EMBEDDING_DIMS,
                    }

                    # 如果用户显式配置了 QDRANT_URL，使用用户配置
                    if plugin_config.QDRANT_URL:
                        base_qdrant_url = plugin_config.QDRANT_URL
                        parsed_url = urlparse(base_qdrant_url)
                        api_key = plugin_config.QDRANT_API_KEY or qdrant_config.api_key

                        if parsed_url.scheme:
                            # 网络地址模式
                            vector_config.update({"url": base_qdrant_url})
                            if api_key:
                                vector_config.update({"api_key": api_key})
                        else:
                            # 本地文件路径模式
                            vector_config.update({"path": base_qdrant_url})
                            if api_key:
                                vector_config.update({"api_key": api_key})
                    else:
                        # 未配置 QDRANT_URL：使用内置 Qdrant 的连接信息
                        # 注意：mem0 不支持 AsyncQdrantClient，需要使用 url/api_key 让 mem0 自己创建同步客户端
                        logger.info("使用 NekroAgent 内置 Qdrant 配置...")
                        if not qdrant_config.url:
                            logger.error("❌ 内置 Qdrant 配置中缺少 URL！")
                            raise ConnectionError("内置 Qdrant 配置中缺少 URL")

                        logger.info(
                            f"✓ Qdrant URL: {qdrant_config.url}, 集合名称: {collection_name}"
                        )
                        vector_config.update(
                            {
                                "url": qdrant_config.url,
                                "api_key": qdrant_config.api_key,
                            }
                        )
                elif plugin_config.VECTOR_DB == "chroma":
                    collection_name = plugin.get_vector_collection_name()
                    vector_config = {
                        "path": plugin_config.CHROMA_PATH,
                        "collection_name": collection_name,
                    }
                elif plugin_config.VECTOR_DB == "redis":
                    collection_name = plugin.get_vector_collection_name()
                    vector_config = {
                        "redis_url": plugin_config.REDIS_URL,
                        "collection_name": collection_name,
                        "embedding_model_dims": plugin_config.EMBEDDING_DIMS,
                    }
                else:
                    raise ValueError(
                        f"暂不支持的向量数据库类型: {plugin_config.VECTOR_DB}"
                    )

                embedder = EmbedderConfig(
                    provider="openai",
                    config={
                        "model": embedding_group.CHAT_MODEL,
                        "embedding_dims": plugin_config.EMBEDDING_DIMS,
                        "api_key": embedding_group.API_KEY,
                        "openai_base_url": embedding_group.BASE_URL or None,
                    },
                )
                llm = LlmConfig(
                    provider="openai",
                    config={
                        "model": llm_group.CHAT_MODEL,
                        "api_key": llm_group.API_KEY,
                        "openai_base_url": llm_group.BASE_URL or None,
                    },
                )
                vector_store = VectorStoreConfig(
                    provider=plugin_config.VECTOR_DB, config=vector_config
                )

                memory_config = MemoryConfig(
                    embedder=embedder,
                    vector_store=vector_store,
                    llm=llm,
                    version="v1.1",  # Required for mem0 v1.0.0+
                )
                _mem0_instance = Memory(config=memory_config)

            _last_config_hash = current_config_hash
            logger.success("✓ mem0客户端实例创建成功")
        except Exception as e:
            logger.error(f"❌ 创建mem0客户端实例失败: {e}")
            logger.error(f"错误类型: {type(e).__name__}")
            import traceback

            logger.error(f"错误堆栈:\n{traceback.format_exc()}")
            _mem0_instance = None

    return _mem0_instance
