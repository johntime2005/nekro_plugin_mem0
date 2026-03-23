# Nekro Agent 长期记忆插件 (nekro-plugin-mem0)

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
- **🔄 智能去重**: SimHash + 多指标相似度评分，自动过滤重复记忆
- **🤖 被动提取**: 每 N 轮对话自动从历史消息中提取结构化记忆
- **✍️ 查询改写**: LLM 改写查询提升检索质量，自动跳过无意义检索
- **🏷️ 增强类型**: 11 种记忆类型 + 重要性评分(1-10) + 过期时间
- **🧠 多引擎支持**: 
  - **Basic**: 向量搜索（默认，向后兼容）
  - **HippoRAG**: 知识图谱 + PPR 多跳推理
  - **EMGAS**: 激活扩散 + 时间衰减

## 🚀 快速开始

### 1. 克隆本仓库

```bash
git clone https://github.com/johntime2005/nekro-plugin-mem0.git
cd nekro-plugin-mem0
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
- `PERSONA_BIND_USER`：为 `True`（默认）时，persona 层会同时使用 `user_id + agent_id` 进行隔离，避免不同用户因为同一 agent_id 产生记忆串用。
- `REDIS_URL`：当 `VECTOR_DB=redis` 时生效，形如 `redis://redis:6379/0`；生产环境请将 Redis 数据目录挂载卷以获得持久化，并可通过更换 URL 在服务器间迁移。
- `LEGACY_SCOPE_FALLBACK_ENABLED`：为 `True`（默认）时，读取会自动回退尝试旧作用域格式（旧 user/agent/run 编码），升级后历史记忆可见性更好。
- `AUTO_MIGRATE_ON_READ`：为 `True` 时，若回退命中旧作用域且新作用域当前为空，会把旧记忆复制到新作用域（默认关闭，建议灰度开启）。

### 去重配置
- `DEDUP_ENABLED` (bool, 默认 True): 启用去重
- `DEDUP_SIMILARITY_THRESHOLD` (float, 默认 0.8): 相似度阈值（0.0-1.0）
- `DEDUP_SIMHASH_THRESHOLD` (int, 默认 10): SimHash Hamming 距离预筛阈值

### 被动提取配置
- `AUTO_EXTRACT_ENABLED` (bool, 默认 True): 启用被动提取
- `AUTO_EXTRACT_INTERVAL` (int, 默认 3): 提取间隔（轮次）
- `AUTO_EXTRACT_TARGET_LAYER` (str, 默认 "persona"): 提取目标层级

### 过期自动清理配置
- `AUTO_CLEANUP_ENABLED` (bool, 默认 True): 启用过期记忆自动清理后台任务
- `AUTO_CLEANUP_INTERVAL_SECONDS` (int, 默认 600): 自动清理间隔秒数（最小 30 秒）

### 查询改写配置
- `QUERY_REWRITE_ENABLED` (bool, 默认 False): 启用查询改写（会增加延迟）

### 引擎配置
- `MEMORY_ENGINE` (str, 默认 "basic"): 记忆引擎选择
  - `"basic"`: 向量搜索（默认，向后兼容）
  - `"hippo"`: HippoRAG 知识图谱引擎
  - `"emgas"`: EMGAS 激活扩散引擎

#### HippoRAG 引擎参数
- `HIPPO_PPR_ALPHA` (float, 默认 0.15): PPR 重启概率
- `HIPPO_HYBRID_WEIGHT` (float, 默认 0.8): 语义相似度权重（1-weight 为 PPR 权重）
- `HIPPO_TOP_ENTITIES` (int, 默认 10): Top 实体数
- `HIPPO_MAX_CANDIDATES` (int, 默认 200): 最大候选记忆数

#### EMGAS 引擎参数
- `EMGAS_DECAY_RATE` (float, 默认 0.01): 时间衰减率 λ
- `EMGAS_PRUNE_THRESHOLD` (float, 默认 0.05): 低激活值剪枝阈值
- `EMGAS_FIRING_THRESHOLD` (float, 默认 0.1): 激活传播触发阈值
- `EMGAS_PROPAGATION_DECAY` (float, 默认 0.85): 能量传播保留比例

## 🛠️ 可用函数 (Agent 可调用)

> ⚠️ **重要：同一组函数有两种调用形态（请按运行环境选择）。**
>
> - **沙盒内（Nekro Agent 运行时）**：第一个参数传 `_ctx`（由运行时注入）。
> - **沙盒外（独立 Python 脚本）**：第一个参数传 `None`，并显式提供 `user_id/agent_id/run_id` 中至少一个作用域标识。
>
> 常见报错根因：在独立脚本里直接照抄 `search_memory(_ctx, ...)`，会触发 `NameError: name '_ctx' is not defined`。

Agent 可以通过以下函数来操作记忆库：

- `add_memory(ctx_or_none, memory, user_id=None, metadata=None, expiration_date=None, agent_id=None, run_id=None, scope_level=None)`
  - **描述**: 添加一条记忆（非阻塞，立即返回；后台异步写入）。
  - **补充**: 可直接传 `expiration_date`（ISO8601）让模型在写入时设置过期时间。

- `search_memory(ctx_or_none, query, user_id=None, agent_id=None, run_id=None, scope_level=None, layers=None, limit=5)`
  - **描述**: 通过语义检索搜索记忆（阻塞直到返回结果）。
  - **边界**: 仅用于“具体语义查询”（如“我喜欢什么”“之前说过XX吗”）。
  - **不要用于**: “列出所有记忆/全部记忆”这类全量枚举诉求（应使用 `get_all_memory`）。
  - **返回补充**: 结果包含 `memory_operations`，提供 `update / update_metadata / delete` 的可调用模板（含 `memory_id`）。

- `get_all_memory(ctx_or_none, user_id=None, agent_id=None, run_id=None, scope_level=None, layers=None, tags=None)`
  - **描述**: 获取指定层级的全部记忆，可按标签过滤。
  - **返回补充**: 同样包含 `memory_operations`，便于模型对单条记忆做后续维护。

- `update_memory(ctx_or_none, memory_id, new_memory)`
  - **描述**: 更新指定记忆内容（非阻塞，后台异步更新）。

- `update_memory_metadata(ctx_or_none, memory_id, metadata_patch=None, expiration_date=None, clear_expiration=False)`
  - **描述**: 仅更新指定记忆元数据（非阻塞，后台异步更新）。
  - **典型用途**: 调整 `TYPE/importance`、设置或清除 `expiration_date`，不改正文内容。

- `delete_memory(ctx_or_none, memory_id)`
  - **描述**: 删除单条记忆（非阻塞，后台异步删除）。

- `delete_all_memory(ctx_or_none, user_id=None, agent_id=None, run_id=None, scope_level=None, layers=None)`
  - **描述**: 删除指定作用域的全部记忆（危险操作）。

- `get_memory_history(ctx_or_none, memory_id)`
  - **描述**: 查看指定记忆的历史版本。

### 调用示例

```python
# 沙盒内（推荐）：_ctx 由运行时注入
result = await search_memory(_ctx, "和主人的记忆", agent_id="xinger", user_id="private_6502612088", layers=["persona", "global"], limit=20)
```

```python
# ❌ 错误：独立脚本里 _ctx 未定义，会直接 NameError
result = await search_memory(_ctx, "和主人的记忆", agent_id="xinger", user_id="private_6502612088")
```

```python
# 列出全量记忆：请使用 get_all_memory（不要用 search_memory("所有记忆")）
result = await get_all_memory(_ctx, agent_id="xinger", user_id="private_6502612088", layers=["persona", "global"])
```

```python
# 沙盒外独立脚本调试：没有 AgentCtx 时传 None，并显式给出作用域标识
result = await search_memory(None, "和主人的记忆", agent_id="xinger", user_id="private_6502612088", layers=["persona", "global"], limit=20)
```

## 💬 聊天指令（免代码）

在聊天中直接使用 `/mem` 风格的命令来查看、删除或添加记忆（需要插件运行在含命令适配器的环境，例如 OneBot）。

> 权限说明：`mem` 命令组默认仅管理员（`SUPER_USER`）可调用。

> 触发语法提示：不同适配器可能显示为 `mem list` 或 `mem.list`，本插件命令组名为 `mem`，子命令包括 `list/search/visual/panel/...`。

> 注意：`/mem` 根命令会返回帮助文本；实际操作请使用 `mem list/search/...` 等子命令。在控制台排查“查不到记忆”时，建议显式传入 `user=xxx agent=xxx run=xxx` 以对齐目标作用域。

- `mem list [layer=conversation|persona|global] [tags=T1,T2]`：按层级列出记忆（默认会话→人设→全局）。
- `mem visual [layer=xxx] [tags=T1,T2] [limit=60]`：输出记忆可视化总览（层级分布、类型分布、重要性、时间线、关系视图）。
- `mem panel [layer=xxx] [tags=T1,T2] [limit=80] [ops=true|false]`：输出可视化管理面板（统计、过期健康度、优先维护列表、快捷管理指令）。
  - `tags` 仅匹配 `metadata.TYPE`；未标注 TYPE 的记忆不会被 tags 命中。
- `mem delete <memory_id>`：删除单条记忆。
- `mem cleanup`：立即触发一次过期记忆清理（管理员权限，别名 `mem prune`）。
- `mem clear [layer=conversation|persona|global]`：按层级清空（不填 layer 按默认顺序）。
- `mem history <memory_id>`：查看指定记忆的历史版本。
- `mem search <query> [layer=xxx] [limit=5]`：语义搜索并展示结果。
- `mem add <文本> [layer=conversation|persona|global] [tag=TYPE] [expires=ISO8601] [meta.xxx=val]`：写入记忆，支持标签、过期时间与自定义元数据。

可选参数：
`user=xxx agent=xxx run=xxx layer=xxx tag=TYPE meta.xxx=val`
（不填则自动使用当前会话/用户推断作用域）。

## 🏷️ 记忆类型标签

插件支持以下 11 种记忆类型标签：

- **FACTS**: 事实信息（姓名、生日、职业）
- **PREFERENCES**: 个人喜好（喜欢古典音乐、讨厌香菜）
- **GOALS**: 目标或愿望（年底前学会 Python）
- **TRAITS**: 人格或习惯（乐观、有晨跑习惯）
- **RELATIONSHIPS**: 人际关系（张三的同事）
- **EVENTS**: 事件或里程碑（上个月参加婚礼）
- **TOPICS**: 讨论过的话题（人工智能）
- **CONTEXTUAL**: 上下文相关信息
- **TEMPORAL**: 时间相关信息、日期
- **TASK**: 任务相关、待办事项
- **SKILL**: 技能、专长、能力
- **INTEREST**: 兴趣爱好、热情所在
- **LOCATION**: 位置相关、地点信息

## 🚀 高级特性

### HippoRAG 引擎

基于知识图谱和 Personalized PageRank (PPR) 的多跳推理引擎。

**特性**:
- 自动提取实体和三元组（subject-predicate-object）
- 实体别名合并（Jaccard 相似度 ≥ 0.85）
- PPR 图游走实现多跳推理
- 混合评分：0.8 × 语义相似度 + 0.2 × PPR 分数
- 知识图谱持久化到 JSON

**适用场景**: 需要关联推理的复杂知识检索（如"我朋友的朋友喜欢什么"）

**启用方式**:
```python
MEMORY_ENGINE = "hippo"
```

### EMGAS 引擎

基于激活扩散的情景记忆图引擎。

**特性**:
- 时间衰减：记忆随时间遗忘（activation × e^(-λ × Δt_hours)）
- 激活扩散：能量在图中传播，模拟人类记忆激活
- 触发阈值：只有激活值超过阈值的节点才传播能量
- 低激活剪枝：定期清理不活跃记忆
- PPMI 边权重：基于共现统计的有意义连接

**适用场景**: 需要时间感知和遗忘机制的长期记忆管理

**启用方式**:
```python
MEMORY_ENGINE = "emgas"
```

### 被动记忆提取

每隔 N 轮对话自动从历史消息中提取关键信息。

**提取优先级**（从高到低）:
1. preferences（偏好）
2. personal（个人信息）
3. interests（兴趣）
4. habits（习惯）
5. skills（技能）
6. relationships（关系）
7. factual（事实）

**提取的记忆包含**:
- content: 记忆内容
- type: 记忆类型（11 种之一）
- importance: 重要性评分（1-10）

**配置示例**:
```python
AUTO_EXTRACT_ENABLED = True
AUTO_EXTRACT_INTERVAL = 3  # 每 3 轮对话触发一次
AUTO_EXTRACT_TARGET_LAYER = "persona"  # 写入 persona 层
```

## 📄 许可证

MIT
