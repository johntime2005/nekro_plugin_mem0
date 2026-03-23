"""
插件配置与实例
"""

from typing import Optional
from nekro_agent.api.plugin import ExtraField
from nekro_agent.services.plugin.base import ConfigBase, NekroPlugin
from pydantic import Field


plugin = NekroPlugin(
    name="记忆插件",
    module_name="nekro_plugin_mem0",
    description="为Nekro Agent提供基于 mem0 v1.0 的长期记忆能力",
    version="1.4.0",
    author="johntime2005",
    url="https://github.com/johntime2005/nekro_plugin_mem0",
)


@plugin.mount_config()
class PluginConfig(ConfigBase):
    """记忆插件配置"""

    MEM0_API_KEY: str = Field(
        default="",
        title="Mem0 API Key",
        description="Mem0服务的API密钥（留空将使用本地向量库）",
        json_schema_extra=ExtraField(
            is_secret=True, load_to_sysenv=True, load_sysenv_as="MEM0_API_KEY"
        ).model_dump(),
    )
    MEM0_BASE_URL: str = Field(
        default="", title="Mem0 Base URL", description="Mem0服务的基础URL（可选）"
    )

    MEMORY_MANAGE_MODEL: str = Field(
        default="default",
        title="记忆管理模型组",
        description="用于总结、更新记忆的对话模型组（直接复用系统已配置的模型）",
        json_schema_extra=ExtraField(
            ref_model_groups=True, model_type="chat", required=True
        ).model_dump(),
    )
    TEXT_EMBEDDING_MODEL: str = Field(
        default="default",
        title="向量嵌入模型组",
        description="用于生成记忆向量的嵌入模型组（直接复用系统已配置的模型）",
        json_schema_extra=ExtraField(
            ref_model_groups=True, model_type="embedding", required=True
        ).model_dump(),
    )
    EMBEDDING_DIMS: int = Field(
        default=1536, title="嵌入维度", description="嵌入向量的维度"
    )

    VECTOR_DB: str = Field(
        default="qdrant", title="向量数据库", description="使用的向量数据库类型"
    )
    QDRANT_URL: str = Field(
        default="",
        title="Qdrant URL",
        description="Qdrant服务器地址（留空将使用内置Qdrant配置）",
        json_schema_extra=ExtraField(placeholder="默认使用内置Qdrant实例").model_dump(),
    )
    QDRANT_API_KEY: str = Field(
        default="", title="Qdrant API Key", description="Qdrant的API密钥（可选）"
    )
    CHROMA_PATH: str = Field(
        default="./chroma_db", title="Chroma DB路径", description="Chroma数据库存储路径"
    )
    REDIS_URL: str = Field(
        default="redis://redis:6379/0",
        title="Redis URL",
        description="Redis 矢量存储地址，适用于 Docker 部署持久化（请将 Redis 数据目录挂载为卷）",
    )
    COLLECTION_NAME: str = Field(
        default="nekro_memories",
        title="向量集合名称",
        description="向量存储使用的集合名称",
    )

    MEMORY_SEARCH_SCORE_THRESHOLD: float = Field(
        default=0.5, title="搜索分数阈值", description="记忆搜索的最低相关度分数"
    )
    IMPORTANCE_WEIGHT: float = Field(
        default=0.3,
        title="重要性权重",
        description="importance 在排序/过滤中的权重（0.0-1.0），剩余为 score 权重。组合分数 = (1-weight)*score + weight*(importance/10)",
    )
    SESSION_ISOLATION: bool = Field(
        default=True, title="会话隔离", description="是否启用会话隔离"
    )
    ENABLE_AGENT_SCOPE: bool = Field(
        default=True,
        title="启用助理级记忆",
        description="为同一 Agent 跨会话复用记忆（同时仍按需要写入用户/会话维度）",
    )
    PERSONA_BIND_USER: bool = Field(
        default=True,
        title="人设层绑定用户",
        description="启用后 persona 层同时使用 user_id+agent_id 进行隔离，避免不同用户共享同一 persona 记忆",
    )
    ENABLE_GUILD_SCOPE: bool = Field(
        default=False,
        title="启用群组层",
        description="启用 Guild 层，允许群组内共享记忆（群聊场景）",
    )
    PRE_SEARCH_ENABLED: bool = Field(
        default=True, title="预搜索启用", description="是否启用预搜索功能"
    )
    PRE_SEARCH_DB_MESSAGE_COUNT: int = Field(
        default=50,
        title="预搜索数据库消息数",
        description="从数据库拉取的历史消息数量（用于生成查询）",
    )
    PRE_SEARCH_QUERY_MESSAGE_COUNT: int = Field(
        default=10,
        title="预搜索查询消息数",
        description="用于生成查询的用户消息数量（从拉取的消息中筛选）",
    )
    PRE_SEARCH_SKIP_CONVERSATION: bool = Field(
        default=True,
        title="预搜索跳过会话层",
        description="跳过 conversation 层搜索（当前对话内容 LLM 已知，跳过可提升性能）",
    )
    PRE_SEARCH_RESULT_LIMIT: int = Field(
        default=5, title="预搜索结果限制", description="每个层级最多返回的记忆数"
    )
    PRE_SEARCH_QUERY_MAX_LENGTH: int = Field(
        default=500,
        title="预搜索查询最大长度",
        description="生成的查询字符串最大字符数（避免过长查询影响性能）",
    )
    PRE_SEARCH_TIMEOUT: float = Field(
        default=0.8,
        title="预搜索超时（秒）",
        description="预搜索总等待时间预算；超时会保留已完成层级结果，仅在全部超时时降级",
    )
    PRE_SEARCH_SCORE_THRESHOLD: Optional[float] = Field(
        default=0.35,
        title="预搜索分数阈值",
        description="预搜索的最低组合分数阈值（None 表示使用 MEMORY_SEARCH_SCORE_THRESHOLD）。预搜索场景建议较低阈值以提高召回率",
    )
    LEGACY_SCOPE_FALLBACK_ENABLED: bool = Field(
        default=True,
        title="启用旧作用域兼容读取",
        description="读取时自动尝试旧 user/agent/run 作用域格式，减少升级后历史记忆不可见问题",
    )
    AUTO_MIGRATE_ON_READ: bool = Field(
        default=False,
        title="读取时自动迁移旧记忆",
        description="在兼容读取命中旧作用域时，自动复制写入当前新作用域（建议灰度开启）",
    )

    DEDUP_ENABLED: bool = Field(
        default=True,
        title="启用去重",
        description="添加记忆前检查重复，避免存储相似内容",
    )
    DEDUP_SIMILARITY_THRESHOLD: float = Field(
        default=0.8,
        title="去重相似度阈值",
        description="相似度超过此值视为重复（0.0-1.0）",
    )
    DEDUP_SIMHASH_THRESHOLD: int = Field(
        default=10,
        title="SimHash 预筛阈值",
        description="Hamming 距离超过此值跳过精确计算（性能优化）",
    )

    AUTO_EXTRACT_ENABLED: bool = Field(
        default=True,
        title="启用被动提取",
        description="每隔 N 轮对话自动从历史消息中提取记忆",
    )
    AUTO_EXTRACT_INTERVAL: int = Field(
        default=3,
        title="提取间隔（轮次）",
        description="每隔多少轮对话触发一次被动提取（1-10）",
    )
    AUTO_EXTRACT_TARGET_LAYER: str = Field(
        default="persona",
        title="提取目标层级",
        description="被动提取的记忆写入哪个层级（conversation/persona/global）",
    )

    QUERY_REWRITE_ENABLED: bool = Field(
        default=False,
        title="启用查询改写",
        description="预搜索时使用 LLM 改写查询以提升检索质量（会增加延迟）",
    )

    MEMORY_ENGINE: str = Field(
        default="basic",
        title="记忆引擎",
        description="选择记忆检索引擎：basic（向量搜索）、hippo（知识图谱+PPR）、emgas（激活扩散）",
    )

    HIPPO_PPR_ALPHA: float = Field(
        default=0.15,
        title="HippoRAG PPR Alpha",
        description="Personalized PageRank 重启概率",
    )
    HIPPO_HYBRID_WEIGHT: float = Field(
        default=0.8,
        title="HippoRAG 混合权重",
        description="语义相似度权重（剩余为 PPR 权重）",
    )
    HIPPO_TOP_ENTITIES: int = Field(
        default=10,
        title="HippoRAG Top 实体数",
        description="PPR 选择前 N 个高分实体",
    )
    HIPPO_MAX_CANDIDATES: int = Field(
        default=200,
        title="HippoRAG 最大候选数",
        description="通过实体获取的最大候选记忆数",
    )

    EMGAS_DECAY_RATE: float = Field(
        default=0.01,
        title="EMGAS 衰减率",
        description="时间衰减参数 λ",
    )
    EMGAS_PRUNE_THRESHOLD: float = Field(
        default=0.05,
        title="EMGAS 剪枝阈值",
        description="低于此激活值的节点被剪枝",
    )
    EMGAS_FIRING_THRESHOLD: float = Field(
        default=0.1,
        title="EMGAS 触发阈值",
        description="节点激活值超过此值才传播能量",
    )
    EMGAS_PROPAGATION_DECAY: float = Field(
        default=0.85,
        title="EMGAS 传播衰减",
        description="能量传播时的保留比例（0.85 = 15% 损失）",
    )

    AUTO_EXPIRATION_ENABLED: bool = Field(
        default=True,
        title="启用自动过期",
        description="根据记忆类型和重要性自动计算过期时间（仅在未显式指定 expiration_date 时生效）",
    )
    ACCESS_REINFORCEMENT_ENABLED: bool = Field(
        default=True,
        title="启用访问强化",
        description="访问记忆时自动延长过期时间并记录访问次数",
    )
    REINFORCEMENT_EXTEND_RATIO: float = Field(
        default=0.2,
        title="强化延长比例",
        description="每次访问延长原始 TTL 的比例（0.2 = 延长 20%）",
    )
    EXPIRY_CLEANUP_INTERVAL: int = Field(
        default=600,
        title="过期清理间隔（秒）",
        description="自动清理过期记忆的间隔时间（秒），最小 60",
    )


_memory_config: Optional[PluginConfig] = None


def get_memory_config() -> PluginConfig:
    global _memory_config
    if _memory_config is None:
        _memory_config = plugin.get_config(PluginConfig)
    return _memory_config
