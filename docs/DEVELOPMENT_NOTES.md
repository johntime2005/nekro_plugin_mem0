# 开发文档归档（合并版）

> 本文档合并自以下历史文档：
> - `chatluna_longmemory_analysis.md`
> - `IMPLEMENTATION_SUMMARY.md`
> - `DIAGNOSTIC_REPORT.md`

## 1. 参考架构要点（ChatLuna long-memory）

- 采用分层记忆（Global / Preset / Guild / User）管理共享边界。
- 提供多引擎检索能力：
  - **Basic**：简单、低成本，适合小规模记忆。
  - **HippoRAG**：知识图谱 + PPR，多跳关联能力强。
  - **EMGAS**：激活扩散 + 时间衰减，强调时序与联想。
- 关键优化思路：查询改写、记忆去重、图谱持久化、批量处理与缓存。

## 2. 本插件预搜索能力实现摘要

### 2.1 新增配置

- `PRE_SEARCH_ENABLED`
- `PRE_SEARCH_DB_MESSAGE_COUNT`
- `PRE_SEARCH_QUERY_MESSAGE_COUNT`
- `PRE_SEARCH_SKIP_CONVERSATION`
- `PRE_SEARCH_RESULT_LIMIT`
- `PRE_SEARCH_QUERY_MAX_LENGTH`
- `PRE_SEARCH_TIMEOUT`

### 2.2 关键模块与职责

- `pre_search_utils.py`
  - `build_pre_search_query()`：基于近期消息构造检索查询。
  - `clean_message_content()`：清洗噪声内容（代码块、标签等）。
  - `convert_db_messages_to_dict()`：数据库消息结构标准化。
- `plugin_method.py`
  - `_fetch_recent_messages()`：拉取并整理最近消息。
  - `_search_single_layer()`：分层检索封装。
  - `_execute_pre_search()`：并行执行预搜索、聚合并格式化结果。
  - `inject_memory_prompt()`：将预搜索结果注入提示词。

### 2.3 设计原则

- 并行检索 + 超时控制，避免阻塞主流程。
- 优雅降级，任一失败不影响基础会话能力。
- 默认跳过 conversation 层以减少重复上下文。

## 3. mem0 / Qdrant 诊断结论

- `Memory.from_config(config)` 配置接收链路正常。
- Qdrant 后端可正确创建集合、写入向量与检索。
- `search/get_all` 需提供 `user_id/agent_id/run_id` 至少一项作用域参数。
- 生产环境建议使用持久化路径或远程 Qdrant 服务，避免 `:memory:` 模式重启丢失。
- 嵌入维度需与模型输出维度严格一致（如 384 / 768 / 1536）。

## 4. 维护建议

- 面向发布的用户文档继续保留在 `README.md`。
- 研发过程资料统一汇总到 `docs/`，避免根目录文档碎片化。
- 本文档作为历史归档入口，后续新增开发报告建议追加到 `docs/` 下。
