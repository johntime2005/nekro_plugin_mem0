# ChatLuna Long-Memory 扩展架构分析

## 1. 基本信息

- **包名**: `koishi-plugin-chatluna-long-memory`
- **版本**: 1.3.3
- **许可**: AGPL-3.0
- **平台**: Koishi 插件生态
- **核心依赖**: 
  - `@langchain/core` ^0.3.80
  - `jieba-wasm` ^2.4.0 (中文分词)
  - `tiny-segmenter` ^0.2.0 (日文分词)
  - `stopwords-iso` ^1.1.0 (停用词)
  - `zod` 3.25.76 (schema 验证)

---

## 2. 核心架构

### 2.1 服务层 (ChatLunaLongMemoryService)

**职责**: 统一管理所有记忆层的生命周期和操作

**核心方法**:
- `initMemoryLayers()` - 初始化指定类型的记忆层
- `retrieveMemory()` - 跨层检索记忆
- `addMemories()` - 添加记忆到指定层
- `deleteMemories()` - 删除记忆
- `updateMemories()` - 更新记忆（带原子性和回滚）
- `clear()` - 清空记忆层

**特性**:
- 自动定期清理过期记忆（每10分钟）
- 支持多层级记忆命名空间管理
- 记忆层创建器注册机制

---

## 3. 记忆分层架构

### 3.1 四层记忆模型

| 层级 | 类型 | 共享范围 | 典型用途 |
|------|------|----------|----------|
| **Global** | 全局层 | 所有用户和会话 | 通用知识库、系统规则、公共信息 |
| **Preset** | 预设层 | 相同预设的对话 | 角色设定、预设背景、角色人格 |
| **Guild** | 群组层 | 同一群组内用户 | 群聊话题、群成员信息、群组事件 |
| **User** | 用户层 | 单个用户的所有对话 | 个人信息、对话历史、个性化记忆 |

### 3.2 记忆层标识

使用 SHA256 哈希生成唯一 ID:
- User: `sha256("user-{userId}")`
- Preset: `sha256("preset-{presetId}")`
- Guild: `sha256("guild-{guildId}")`
- Global: `sha256("global")`

---

## 4. 三种记忆引擎

### 4.1 Basic 引擎

**算法**: 无过滤，直接返回所有记忆

**特点**:
- ✅ 无需向量数据库和嵌入模型
- ✅ 零额外调用成本
- ✅ 实现简单
- ⚠️ 记忆量大时占用大量上下文

**适用场景**: 小到中等记忆量（< 100 条）

---

### 4.2 HippoRAG 引擎

**算法**: 知识图谱 + Personalized PageRank (PPR)

**核心流程**:
1. **实体提取**: 从对话中提取实体和关系
2. **知识图谱构建**: 实体作为节点，关系作为边
3. **PPR 检索**: 基于查询种子实体进行图游走
4. **混合重排**: 结合语义相似度和 PPR 分数

**关键配置**:
```typescript
{
  hippoSimilarityThreshold: 0.35,    // 最终得分阈值
  hippoPPRAlpha: 0.15,               // PPR 随机游走参数
  hippoTopEntities: 10,              // 高分实体数量
  hippoMaxCandidates: 200,           // 候选记忆上限
  hippoHybridWeight: 0.8,            // 混合权重 (语义:PPR = 0.8:0.2)
  hippoIEEnabled: true,              // 启用三元组抽取
  hippoBridgeThreshold: 0.6,         // 实体桥接阈值
  hippoAliasThreshold: 0.85,         // 实体别名合并阈值
  hippoKGPersist: true               // 持久化知识图谱
}
```

**特性**:
- ✅ 支持大规模记忆存储
- ✅ 多跳推理和关联检索
- ✅ 实体别名自动合并
- ✅ 知识图谱持久化到磁盘
- ✅ 使用即强化机制（访问计数）
- ⚠️ 需要额外的 LLM 调用（三元组抽取）

**适用场景**: 中到大记忆量（100-10000+ 条）

---

### 4.3 EMGAS 引擎

**算法**: Episodic Memory Graph with Activation Spreading（激活扩散）

**核心机制**:
1. **概念节点**: 从记忆中提取概念和主题
2. **激活扩散**: 从种子节点传播激活能量
3. **时间衰减**: 记忆随时间自然遗忘
4. **记忆强化**: 访问频繁的记忆激活值更高

**关键配置**:
```typescript
{
  emgasDecayRate: 0.01,              // 时间衰减率 λ
  emgasPruneThreshold: 0.05,         // 低激活节点修剪阈值
  emgasFiringThreshold: 0.1,         // 点火阈值 F
  emgasPropagationDecay: 0.85,       // 传播衰减 D
  emgasMaxIterations: 5,             // 最大迭代次数
  emgasTopN: 20                      // 候选记忆数量
}
```

**特性**:
- ✅ 轻量级图谱结构
- ✅ 计算成本低于 HippoRAG
- ✅ 内置时间衰减和记忆强化
- ✅ 增量式构建
- ✅ 联想检索能力

**适用场景**: 中到大记忆量，注重时间衰减和联想

---

## 5. 记忆类型系统

```typescript
enum MemoryType {
  FACTUAL = 'factual',           // 事实性知识（长期）
  PREFERENCE = 'preference',     // 用户偏好（长期）
  PERSONAL = 'personal',         // 个人信息（长期）
  CONTEXTUAL = 'contextual',     // 上下文相关（中期）
  TEMPORAL = 'temporal',         // 时间相关（短期）
  TASK = 'task',                 // 任务相关（中期）
  SKILL = 'skill',               // 技能相关（长期）
  INTEREST = 'interest',         // 兴趣爱好（长期）
  EVENT = 'event',               // 事件相关（短期）
  LOCATION = 'location',         // 位置相关（中期）
  RELATIONSHIP = 'relationship'  // 关系相关（长期）
}
```

**记忆结构**:
```typescript
interface EnhancedMemory {
  content: string              // 记忆内容
  type: MemoryType            // 记忆类型
  importance: number          // 重要性 (1-10)
  expirationDate?: Date       // 过期时间（可选）
  id: string                  // 唯一标识
  retrievalLayer?: MemoryRetrievalLayerType
}
```

---

## 6. 记忆提取机制

### 6.1 被动提取（基于轮次）

**触发条件**: 每 N 轮对话（默认 3 轮）

**流程**:
1. 选择最近 N 轮对话历史
2. 使用 LLM 提取关键信息
3. 生成 `EnhancedMemory` 对象
4. 存储到 User 层

**配置**:
- `longMemoryExtractModel`: 提取模型（推荐 gpt-4o-mini）
- `longMemoryExtractInterval`: 提取间隔轮次（3-5 推荐）

### 6.2 主动提取（Agent 工具）

**机制**: 注册为 ChatLuna Agent 工具，由模型主动决定何时添加记忆

**优势**: 
- 更精准的记忆时机
- 减少冗余记忆
- 无需配置提取模型

---

## 7. 记忆检索流程

### 7.1 查询改写（Query Rewrite）

**配置**: `longMemoryQueryRewrite: true`

**流程**:
1. 获取最近对话历史
2. 使用 LLM 生成更适合检索的查询
3. 如果返回 `[skip]` 则跳过检索

### 7.2 HippoRAG 检索详细流程

```
用户查询
  ↓
1. 向量存储检索（语义相似度）
  ↓
2. 提取查询中的种子实体
  ↓
3. PPR 图游走（多跳推理）
  ↓
4. 获取 KG 候选记忆
  ↓
5. 合并向量检索 + KG 候选
  ↓
6. 混合重排（语义 × 0.8 + PPR × 0.2）
  ↓
7. 过滤低于阈值的结果
  ↓
8. 更新访问统计（使用即强化）
  ↓
返回记忆列表
```

### 7.3 相似度计算

**HippoRAG 使用**:
- **SimHash**: 快速文本指纹（用于去重和缓存）
- **语义相似度**: 向量嵌入余弦相似度
- **PPR 分数**: 图算法计算的关联度
- **混合得分**: `final = w × semantic + (1-w) × ppr`

---

## 8. 向量数据库集成

**存储方式**: 通过 ChatLuna 的向量存储服务

**支持的向量数据库**:
- Faiss
- Chroma
- Qdrant
- Pinecone
- 其他 LangChain 兼容的向量存储

**文档元数据**:
```typescript
{
  simhash: string,           // SimHash 指纹
  last_accessed: string,     // 最后访问时间 (ISO)
  access_count: number,      // 访问次数
  expirationDate?: string,   // 过期时间
  importance: number,        // 重要性
  type: MemoryType          // 记忆类型
}
```

---

## 9. 插件系统

**插件列表** (位于 `src/plugins/`):

| 插件 | 功能 |
|------|------|
| `add_memory` | 手动添加记忆命令 |
| `chat_middleware` | 聊天前后的记忆处理中间件 |
| `clear_memory` | 清除记忆命令 |
| `config` | 配置管理 |
| `delete_memory` | 删除记忆命令 |
| `edit_memory` | 编辑记忆命令 |
| `init_layer` | 初始化记忆层 |
| `prompt_varaiable` | 渲染模板函数 `{long_memory()}` |
| `search_memory` | 搜索记忆命令 |
| `tool` | Agent 工具注册 |

---

## 10. 渲染模板函数

**语法**:
```javascript
{long_memory('global', 'guild', 'user')}
```

**用途**: 在 ChatLuna 预设中嵌入记忆检索

**示例**:
```
你是一个助手。以下是相关记忆：

{long_memory('user', 'guild')}

请基于这些记忆回答用户问题。
```

---

## 11. 去重机制

### 11.1 SimHash 指纹

**算法**: 局部敏感哈希（LSH）

**用途**:
- 快速检测相似记忆
- 缓存文档映射
- KG 节点标识

### 11.2 向量相似度过滤

**阈值**: 0.8（硬编码）

**流程**: 添加新记忆前，检查向量存储中是否存在高度相似的记忆

---

## 12. 知识图谱持久化

**存储路径**: `data/chatluna/long-memory/hippo/{memoryId}.json`

**格式**:
```json
{
  "entities": [...],
  "edges": [...],
  "memoryToEntities": {...}
}
```

**优势**:
- 重启无需重建 KG
- 加速初始化
- 保留实体关系

---

## 13. 性能优化

### 13.1 批处理

- 嵌入计算批量处理
- 增量图更新

### 13.2 缓存

- SimHash 文档缓存（内存）
- 知识图谱持久化（磁盘）

### 13.3 限制

- 最大候选数: 200（HippoRAG）
- 最大列表限制: 10000
- 强化 Top-K: 10

---

## 14. 命令系统

**用户命令**:
- 清除（所有的）长期记忆
- 修改长期记忆
- 删除长期记忆
- 添加长期记忆
- 搜索长期记忆

---

## 15. 与 mem0 的关键差异

| 特性 | ChatLuna Long-Memory | mem0 |
|------|---------------------|------|
| **记忆分层** | 4 层（Global/Preset/Guild/User） | 通常单层或简单分层 |
| **记忆引擎** | 3 种（Basic/HippoRAG/EMGAS） | 通常单一引擎 |
| **知识图谱** | HippoRAG 内置 KG + PPR | 可能无 KG |
| **时间衰减** | EMGAS 内置 | 需自行实现 |
| **实体别名** | HippoRAG 自动合并 | 需自行实现 |
| **记忆类型** | 11 种细分类型 | 通常简单分类 |
| **平台集成** | Koishi 生态深度集成 | 独立服务 |
| **Agent 工具** | 主动提取支持 | 需自行集成 |
| **渲染模板** | 内置模板函数 | 需自行实现 |

---

## 16. 技术亮点

1. **多引擎架构**: 根据场景选择最优引擎
2. **分层记忆**: 精细化的共享范围控制
3. **知识图谱**: HippoRAG 的多跳推理能力
4. **激活扩散**: EMGAS 的联想检索
5. **使用即强化**: 访问频繁的记忆权重更高
6. **原子性更新**: 带回滚的记忆更新
7. **自动过期清理**: 定期清理过期记忆
8. **SimHash 去重**: 高效的相似记忆检测
9. **查询改写**: 提升检索准确性
10. **持久化 KG**: 加速重启恢复

---

## 17. 配置复杂度

**优势**: 高度可配置，适应不同场景

**劣势**: 配置项多达 20+，学习曲线陡峭

**推荐配置**:
```typescript
// 小型应用（< 100 条记忆）
{
  enabledLayers: ['User'],
  layerEngines: [{ layer: 'User', engine: 'Basic' }]
}

// 中型应用（100-1000 条记忆）
{
  enabledLayers: ['User', 'Guild'],
  layerEngines: [
    { layer: 'User', engine: 'HippoRAG' },
    { layer: 'Guild', engine: 'HippoRAG' }
  ],
  longMemoryExtractInterval: 3
}

// 大型应用（1000+ 条记忆）
{
  enabledLayers: ['Global', 'Guild', 'User'],
  layerEngines: [
    { layer: 'Global', engine: 'Basic' },
    { layer: 'Guild', engine: 'EMGAS' },
    { layer: 'User', engine: 'HippoRAG' }
  ],
  hippoKGPersist: true,
  longMemoryExtractInterval: 5
}
```

---

## 18. 总结

ChatLuna long-memory 是一个**功能丰富、架构复杂**的长期记忆解决方案：

**核心优势**:
- 多层级记忆架构
- 三种可选引擎（Basic/HippoRAG/EMGAS）
- 知识图谱和激活扩散算法
- 深度集成 Koishi 和 ChatLuna 生态

**适用场景**:
- 需要复杂记忆管理的聊天机器人
- 多用户/多群组场景
- 需要知识图谱推理的应用

**学习成本**: 高（配置项多，概念复杂）

**性能**: 优秀（批处理、缓存、持久化）
