# Nekro Agent 长期记忆插件 (nekro-plugin-memory)

> 一个为 NekroAgent 提供强大长期记忆能力的插件，基于 [mem0](https://github.com/mem0-ai/mem0) 实现。

## ✨ 核心功能

- **🧠 长期记忆**: 让 Agent 能够跨越多个会话，持续记忆和遗忘关键信息。
- **🔍 智能搜索**: 支持基于自然语言的语义搜索，能根据上下文智能检索相关记忆。
- **🔗 模型联动**: 自动与 Nekro Agent 当前使用的语言模型（LLM）保持一致，无需为插件单独配置模型，实现无缝集成。
- **⚙️ 高度可配**:
  - 支持自定义 `Agent ID`，为不同的 Agent 或场景隔离记忆。
  - 支持配置不同的 `Embedding` 模型。
  - **解决了维度不匹配问题**：允许显式设置 `Embedding` 维度，完美支持 `text-embedding-004` (768维) 等模型。
- **🧩 多层记忆互通**：基于 mem0 v1.0 的多层记忆架构，支持在同一个用户、Agent 与会话（run）之间同步写入，让助理能在多会话间共享记忆，同时仍可按需启用会话级隔离。
- **💾 多种后端**: 支持 `Qdrant`, `Chroma`, `Redis` 等多种向量数据库作为记忆存储后端，Redis 方案便于 Docker 部署时通过数据卷持久化和迁移。

## 🚀 快速开始

### 1. 克隆本仓库

```bash
git clone https://github.com/johntime2005/nekro-plugin-memory.git
cd nekro-plugin-memory
```

### 2. 安装依赖

本项目使用 [Poetry](https://python-poetry.org/) 进行依赖管理。

```bash
# 安装 poetry 包管理工具
pip install poetry

# 设置虚拟环境目录在项目下 (可选)
poetry config virtualenvs.in-project true

# 安装所有依赖
poetry install
```

## 📝 插件配置

插件加载后，你可以在 Nekro Agent 的配置页面中找到以下参数进行调整：

```python
class MemoryConfig(ConfigBase):
    """长期记忆插件配置"""

    agent_id: str = Field(
        default="nekro-agent",
        title="Agent ID",
        description="用于隔离不同 Agent 记忆的唯一标识符。",
    )
    embedding_model: str = Field(
        default="text-embedding-3-large",
        title="Embedding 模型",
        description="用于将文本向量化的嵌入模型。",
    )
    embedding_dims: int = Field(
        default=1536,
        title="Embedding 维度",
        description="指定嵌入模型的输出维度。例如，对于 text-embedding-004 使用 768，对于 text-embedding-3-large 使用 1536 或 3072。",
    )
    vector_store_provider: str = Field(
        default="qdrant",
        title="向量数据库提供商",
        description="支持 'qdrant', 'chroma' 等。",
    )
    qdrant_host: str = Field(
        default="localhost",
        title="Qdrant 主机地址",
        description="如果使用 Qdrant，请指定其主机地址。",
    )
    qdrant_port: int = Field(
        default=6333,
        title="Qdrant 端口",
        description="如果使用 Qdrant，请指定其端口。",
    )
```

- `COLLECTION_NAME`：控制向量库集合名称，便于与既有实例隔离/共享。
- `ENABLE_AGENT_SCOPE`：开启后会为同一 Agent 写入一份可跨会话复用的记忆；关闭则仅按用户/会话维度写入。
- `SESSION_ISOLATION`：为 `True` 时搜索会优先使用会话 `run_id` 限定结果；设为 `False` 则基于用户/Agent 级别跨会话聚合记忆，满足多轮互通。
- `REDIS_URL`：当 `VECTOR_DB=redis` 时生效，形如 `redis://redis:6379/0`；生产环境请将 Redis 数据目录挂载卷以获得持久化，并可通过更换 URL 在服务器间迁移。

## 🛠️ 可用函数 (Agent 可调用)

Agent 可以通过以下函数来操作记忆库：

- `add_memory(memory: str, user_id: str, metadata: dict)`
  - **描述**: 为用户的个人资料添加一条新记忆，添加的记忆与该用户相关。
  - **参数**:
    - `memory`: 要添加的记忆文本内容
    - `user_id`: 关联的用户ID
    - `metadata`: 元数据标签，支持 TYPE 标签分类记忆

- `search_memory(query: str, user_id: str, tags: list = None)`
  - **描述**: 通过自然语言问句检索指定用户的相关记忆。
  - **参数**:
    - `query`: 查询语句，自然语言问题或关键词
    - `user_id`: 关联的用户ID
    - `tags`: 可选的记忆类型标签过滤列表

- `get_all_memory(user_id: str, tags: list = None)`
  - **描述**: 获取指定用户的所有记忆，支持按标签过滤。
  - **参数**:
    - `user_id`: 关联的用户ID
    - `tags`: 可选的记忆类型标签过滤列表

- `delete_all_memory(user_id: str)`
  - **描述**: 删除指定用户的所有记忆。
  - **参数**:
    - `user_id`: 关联的用户ID

## 🏷️ 记忆类型标签

插件支持以下记忆类型标签来分类不同类型的记忆：

- **FACTS**: 适用于短期内不会改变的事实信息，如姓名、生日、职业等
- **PREFERENCES**: 适用于用户的个人喜好，如"喜欢古典音乐"、"讨厌吃香菜"
- **GOALS**: 适用于用户的目标或愿望，如"想在年底前学会Python"
- **TRAITS**: 适用于描述用户的人格或习惯，如"是乐观的人"、"有晨跑习惯"
- **RELATIONSHIPS**: 适用于记录用户的人际关系，如"是张三的同事"
- **EVENTS**: 适用于记录事件或里程碑，如"上个月参加了婚礼"
- **TOPICS**: 适用于记录用户讨论过的话题，如"讨论过人工智能"

## 📄 许可证

MIT
