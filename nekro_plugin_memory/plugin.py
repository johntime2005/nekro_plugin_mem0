"""
插件配置与实例
"""

from typing import Optional
from nekro_agent.api.plugin import ExtraField
from nekro_agent.services.plugin.base import ConfigBase, NekroPlugin
from pydantic import Field


plugin = NekroPlugin(
    name="记忆插件",
    module_name="nekro_plugin_memory",
    description="为Nekro Agent提供基于 mem0 v1.0 的长期记忆能力",
    version="1.3.0",
    author="johntime2005",
    url="https://github.com/johntime2005/nekro-plugin-memory",
)


@plugin.mount_config()
class PluginConfig(ConfigBase):
    """记忆插件配置"""

    MEM0_API_KEY: str = Field(
        default="",
        title="Mem0 API Key",
        description="Mem0服务的API密钥（留空将使用本地向量库）",
        json_schema_extra=ExtraField(is_secret=True, load_to_sysenv=True, load_sysenv_as="MEM0_API_KEY").model_dump(),
    )
    MEM0_BASE_URL: str = Field(default="", title="Mem0 Base URL", description="Mem0服务的基础URL（可选）")

    MEMORY_MANAGE_MODEL: str = Field(
        default="default",
        title="记忆管理模型组",
        description="用于总结、更新记忆的对话模型组（直接复用系统已配置的模型）",
        json_schema_extra=ExtraField(ref_model_groups=True, model_type="chat", required=True).model_dump(),
    )
    TEXT_EMBEDDING_MODEL: str = Field(
        default="default",
        title="向量嵌入模型组",
        description="用于生成记忆向量的嵌入模型组（直接复用系统已配置的模型）",
        json_schema_extra=ExtraField(ref_model_groups=True, model_type="embedding", required=True).model_dump(),
    )
    EMBEDDING_DIMS: int = Field(default=1536, title="嵌入维度", description="嵌入向量的维度")

    VECTOR_DB: str = Field(default="qdrant", title="向量数据库", description="使用的向量数据库类型")
    QDRANT_URL: str = Field(
        default="",
        title="Qdrant URL",
        description="Qdrant服务器地址（留空将使用内置Qdrant配置）",
        json_schema_extra=ExtraField(placeholder="默认使用内置Qdrant实例").model_dump(),
    )
    QDRANT_API_KEY: str = Field(default="", title="Qdrant API Key", description="Qdrant的API密钥（可选）")
    CHROMA_PATH: str = Field(default="./chroma_db", title="Chroma DB路径", description="Chroma数据库存储路径")
    REDIS_URL: str = Field(
        default="redis://redis:6379/0",
        title="Redis URL",
        description="Redis 矢量存储地址，适用于 Docker 部署持久化（请将 Redis 数据目录挂载为卷）",
    )
    COLLECTION_NAME: str = Field(default="nekro_memories", title="向量集合名称", description="向量存储使用的集合名称")

    MEMORY_SEARCH_SCORE_THRESHOLD: float = Field(default=0.7, title="搜索分数阈值", description="记忆搜索的最低相关度分数")
    SESSION_ISOLATION: bool = Field(default=True, title="会话隔离", description="是否启用会话隔离")
    ENABLE_AGENT_SCOPE: bool = Field(
        default=True,
        title="启用助理级记忆",
        description="为同一 Agent 跨会话复用记忆（同时仍按需要写入用户/会话维度）",
    )
    PRE_SEARCH_ENABLED: bool = Field(default=True, title="预搜索启用", description="是否启用预搜索功能")
    PRE_SEARCH_MESSAGE_COUNT: int = Field(default=50, title="预搜索消息数量", description="预搜索时获取的历史消息数量")


_memory_config: Optional[PluginConfig] = None


def get_memory_config() -> PluginConfig:
    global _memory_config
    if _memory_config is None:
        _memory_config = PluginConfig()
    return _memory_config
