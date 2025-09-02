"""
插件配置与实例
"""

from typing import Optional
from nekro_agent.services.plugin.base import ConfigBase, NekroPlugin
from pydantic import Field


class PluginConfig(ConfigBase):
    """记忆插件配置"""

    OPENAI_API_KEY: str = Field(default="", title="OpenAI API Key", description="用于LLM的OpenAI API密钥")
    MEM0_API_KEY: str = Field(default="", title="Mem0 API Key", description="Mem0服务的API密钥")
    MEM0_BASE_URL: str = Field(default="", title="Mem0 Base URL", description="Mem0服务的基础URL（可选）")

    VECTOR_DB: str = Field(default="qdrant", title="向量数据库", description="使用的向量数据库类型")
    QDRANT_URL: str = Field(default="http://localhost:6333", title="Qdrant URL", description="Qdrant服务器地址")
    QDRANT_API_KEY: str = Field(default="", title="Qdrant API Key", description="Qdrant的API密钥（可选）")
    CHROMA_PATH: str = Field(default="./chroma_db", title="Chroma DB路径", description="Chroma数据库存储路径")

    EMBEDDING_MODEL: str = Field(default="text-embedding-3-large", title="嵌入模型", description="使用的文本嵌入模型")
    EMBEDDING_DIMS: int = Field(default=1536, title="嵌入维度", description="嵌入向量的维度")

    MEMORY_SEARCH_SCORE_THRESHOLD: float = Field(default=0.7, title="搜索分数阈值", description="记忆搜索的最低相关度分数")
    SESSION_ISOLATION: bool = Field(default=True, title="会话隔离", description="是否启用会话隔离")
    PRE_SEARCH_ENABLED: bool = Field(default=True, title="预搜索启用", description="是否启用预搜索功能")
    PRE_SEARCH_MESSAGE_COUNT: int = Field(default=50, title="预搜索消息数量", description="预搜索时获取的历史消息数量")


_memory_config: Optional[PluginConfig] = None


def get_memory_config() -> PluginConfig:
    global _memory_config
    if _memory_config is None:
        _memory_config = PluginConfig()
    return _memory_config


plugin = NekroPlugin(
    name="记忆插件",
    module_name="nekro-plugin-memory",
    description="为Nekro Agent提供基于mem0的长期记忆能力",
    version="1.1.0",
    author="johntime2005",
    url="https://github.com/johntime2005/nekro-plugin-memory",
)
