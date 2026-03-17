# 修复 PreSearch 阈值过滤系统

## TL;DR

> **Quick Summary**: PreSearch 每次都触发"阈值过滤后为空，回退为低阈值结果注入"，根因是组合分数公式硬编码权重过严（需 raw score ≥ 0.786 才能过线）、EMGAS 引擎不返回 score 字段（组合分数恒 ≤ 0.15）、以及 `IMPORTANCE_WEIGHT` 配置虽存在但从未被代码引用。本计划通过统一评分函数、补齐 EMGAS score、新增 PreSearch 专用阈值、降噪日志来系统性修复。
>
> **Deliverables**:
> - 统一的 `_get_combined_score` 函数（消除 4 处重复硬编码）
> - EMGAS 引擎返回归一化 score 字段
> - 新增 `PRE_SEARCH_SCORE_THRESHOLD` 配置项
> - 回退日志降级 + 诊断日志
> - 完整测试覆盖
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7

---

## Context

### Original Request
用户报告 PreSearch 一直打印 `[INFO] [PreSearch] 阈值过滤后为空，回退为低阈值结果注入`，严重影响功能。

### Interview Summary
**Key Discussions**:
- 日志来源：`plugin_method.py:1453`，每次预搜索都触发
- 根因：组合分数公式 `0.7*score + 0.3*(importance/10)` 在 4 处硬编码，阈值 0.7 过严
- EMGAS 引擎 `search_memory()` 返回结果不含 `score` 字段
- `IMPORTANCE_WEIGHT` 配置存在但从未被代码使用

**Research Findings**:
- Oracle 确认：在当前参数下重复回退是预期行为，非代码缺陷
- 3 个 explore agent 确认完整调用链
- EMGAS `retrieve_context()` 返回 `set[str]`（丢弃了激活分数）
- `emgas_spreading.py:113` 中激活分数存在但被丢弃

### Metis Review
**Identified Gaps** (addressed):
- EMGAS 激活分数归一化策略需明确（min-max + 除零保护）
- `retrieve_context()` 返回类型变更需向后兼容
- 测试 stub `_DummyPluginConfig` 需更新
- `dedup_similarity.py` 的 `combined_score` 完全无关，不可触碰

---

## Work Objectives

### Core Objective
修复 PreSearch 阈值过滤系统，使其在各引擎（Basic/Hippo/EMGAS）下正常工作，不再频繁触发无意义回退。

### Concrete Deliverables
- `mem0_output_formatter.py`: 统一 `_get_combined_score` 支持 `importance_weight` 参数
- `plugin_method.py`: 3 处内联 `_get_combined_score` 替换为调用统一版本
- `memory_engine_emgas.py`: `search_memory()` 返回带 `score` 字段的结果
- `emgas_spreading.py`: `retrieve_context()` 返回 `dict[str, float]`
- `plugin.py`: 新增 `PRE_SEARCH_SCORE_THRESHOLD` 配置（默认 0.35）
- `test_memory_scope_risks.py`: 更新测试 stub + 新增回归测试

### Definition of Done
- [ ] `grep -rn "0\.7 \* score" *.py` 排除 `dedup_similarity.py` 后返回 0 匹配
- [ ] `grep -rn "IMPORTANCE_WEIGHT" *.py` 返回 ≥ 3 匹配（配置定义 + 使用点）
- [ ] EMGAS `search_memory()` 结果均含 `score` 字段且 `0.0 <= score <= 1.0`
- [ ] PreSearch 使用 EMGAS 引擎 + 默认配置时不触发回退日志
- [ ] 所有现有测试通过

### Must Have
- 统一评分函数使用配置权重
- EMGAS 返回有效 score
- PreSearch 专用阈值配置
- 回退日志降级

### Must NOT Have (Guardrails)
- 不触碰 `dedup_similarity.py`（其 `combined_score` 是完全不同的去重公式）
- 不破坏 `format_search_output` 函数签名（仅添加可选参数）
- 默认配置下评分行为不变（`IMPORTANCE_WEIGHT=0.3` 等价于当前硬编码 `0.7/0.3`）
- 不修改 EMGAS 图持久化格式（`save()`/`load()`）
- 不在评分函数中添加引擎类型感知
- 不重构评分/阈值/EMGAS-score 范围之外的代码

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES（`test_memory_scope_risks.py` 已有测试框架）
- **Automated tests**: YES (Tests-after，每个 commit 附带测试)
- **Framework**: python -m pytest（项目已有 pytest 风格测试）

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Library/Module**: Use Bash (python REPL) — Import, call functions, compare output
- **Code Quality**: Use Bash (grep/ast_grep) — Verify no hardcoded patterns remain

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — foundation):
├── Task 1: 统一 _get_combined_score 函数 [quick]
├── Task 2: EMGAS retrieve_context 返回激活分数 [unspecified-high]

Wave 2 (After Wave 1 — wiring):
├── Task 3: EMGAS search_memory 注入 score 字段 (depends: 2) [quick]
├── Task 4: plugin_method.py 替换 3 处硬编码评分 (depends: 1) [quick]
├── Task 5: 新增 PRE_SEARCH_SCORE_THRESHOLD 配置 + 接入 (depends: 1) [quick]

Wave 3 (After Wave 2 — polish + verify):
├── Task 6: 日志降级 + 诊断日志 (depends: 4, 5) [quick]
├── Task 7: 更新测试 stub + 全量回归 (depends: 1-6) [unspecified-high]

Wave FINAL (After ALL tasks):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real QA (unspecified-high)
├── Task F4: Scope fidelity check (deep)

Critical Path: Task 1 → Task 4 → Task 5 → Task 6 → Task 7 → F1-F4
Parallel Speedup: ~40% faster than sequential
Max Concurrent: 2 (Wave 1)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | — | 3, 4, 5 |
| 2 | — | 3 |
| 3 | 2 | 7 |
| 4 | 1 | 6, 7 |
| 5 | 1 | 6, 7 |
| 6 | 4, 5 | 7 |
| 7 | 1-6 | F1-F4 |

### Agent Dispatch Summary

- **Wave 1**: 2 tasks — T1 → `quick`, T2 → `unspecified-high`
- **Wave 2**: 3 tasks — T3 → `quick`, T4 → `quick`, T5 → `quick`
- **Wave 3**: 2 tasks — T6 → `quick`, T7 → `unspecified-high`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [ ] 1. 统一 `_get_combined_score` 函数，支持可配置权重

  **What to do**:
  - 修改 `mem0_output_formatter.py` 中的 `_get_combined_score`，添加 `importance_weight: float = 0.3` 参数
  - 公式改为 `(1.0 - w) * score + w * (importance / 10.0)`，其中 `w = max(0.0, min(1.0, importance_weight))`
  - 保留现有的 `isinstance` 类型检查和 importance clamp 逻辑
  - 修改 `format_search_output` 添加可选参数 `importance_weight: float = 0.3`，透传给 `_get_combined_score`
  - 确保默认参数 `0.3` 产生与当前硬编码 `0.7*score + 0.3*(importance/10)` 完全一致的结果

  **Must NOT do**:
  - 不改变 `format_search_output` 的必选参数签名
  - 不触碰 `dedup_similarity.py`

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单文件修改，逻辑清晰，改动量小
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `playwright`: 无 UI 相关

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 2)
  - **Blocks**: Tasks 3, 4, 5
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `mem0_output_formatter.py:120-133` — 当前 `_get_combined_score` 实现（canonical，有 isinstance 守卫）
  - `mem0_output_formatter.py:136-146` — 当前 `format_search_output` 签名和阈值过滤逻辑

  **API/Type References**:
  - `plugin.py:86-90` — `IMPORTANCE_WEIGHT` 配置定义（default=0.3），描述中已写明公式

  **WHY Each Reference Matters**:
  - `_get_combined_score` 是唯一带 `isinstance` 守卫的版本，应作为统一后的基础
  - `IMPORTANCE_WEIGHT` 的描述文档已写明公式 `(1-weight)*score + weight*(importance/10)`，代码需与之一致

  **Acceptance Criteria**:
  - [ ] `_get_combined_score({"score": 0.8, "metadata": {"importance": 5}})` 返回 `0.7*0.8 + 0.3*0.5 = 0.71`
  - [ ] `_get_combined_score({"score": 0.8, "metadata": {"importance": 5}}, importance_weight=0.5)` 返回 `0.5*0.8 + 0.5*0.5 = 0.65`
  - [ ] `_get_combined_score({"score": None})` 返回 `0.0 + 0.3*0.5 = 0.15`（不崩溃）
  - [ ] `format_search_output([...], threshold=0.7)` 行为与修改前一致（默认权重）

  **QA Scenarios**:

  ```
  Scenario: 默认权重回归验证
    Tool: Bash (python)
    Preconditions: mem0_output_formatter.py 已修改
    Steps:
      1. python -c "from mem0_output_formatter import _get_combined_score; print(_get_combined_score({'score': 0.8, 'metadata': {'importance': 5}}))"
      2. 断言输出 == 0.71
    Expected Result: 0.71（与修改前硬编码结果一致）
    Failure Indicators: 输出不等于 0.71
    Evidence: .sisyphus/evidence/task-1-default-weight.txt

  Scenario: 自定义权重生效
    Tool: Bash (python)
    Preconditions: 同上
    Steps:
      1. python -c "from mem0_output_formatter import _get_combined_score; print(_get_combined_score({'score': 0.8, 'metadata': {'importance': 5}}, importance_weight=0.5))"
      2. 断言输出 == 0.65
    Expected Result: 0.65
    Failure Indicators: 输出不等于 0.65
    Evidence: .sisyphus/evidence/task-1-custom-weight.txt

  Scenario: score 缺失不崩溃
    Tool: Bash (python)
    Preconditions: 同上
    Steps:
      1. python -c "from mem0_output_formatter import _get_combined_score; print(_get_combined_score({}))"
      2. 断言输出 == 0.15
    Expected Result: 0.15
    Failure Indicators: 抛出异常或输出非 0.15
    Evidence: .sisyphus/evidence/task-1-missing-score.txt
  ```

  **Commit**: YES
  - Message: `fix(scoring): unify _get_combined_score with configurable importance_weight`
  - Files: `mem0_output_formatter.py`
  - Pre-commit: `python -c "from mem0_output_formatter import _get_combined_score, format_search_output; print('OK')"`

- [ ] 2. EMGAS `retrieve_context` 返回激活分数

  **What to do**:
  - 修改 `emgas_spreading.py` 中 `EMGASGraph.retrieve_context()` 方法
  - 当前返回 `set[str]`（passage IDs），改为返回 `dict[str, float]`（passage_id → 归一化激活分数）
  - 在 `retrieve_context` 内部，`ranked` 变量（line ~113）已有 `(node_id, activation_score)` 元组，当前只取 node_id 丢弃 score
  - 收集所有 passage_id 对应的激活分数，用 min-max 归一化到 0.0-1.0
  - 除零保护：如果所有激活分数相等，全部设为 1.0
  - 不修改 `save()`/`load()` 序列化格式

  **Must NOT do**:
  - 不修改 EMGASGraph 的持久化格式
  - 不改变 `add_memory`/`remove_memory` 等其他方法

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要理解激活扩散算法的数据流，修改返回类型需谨慎
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 1)
  - **Blocks**: Task 3
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `emgas_spreading.py:85-125` — `retrieve_context()` 当前实现，line 113 有 `ranked = sorted(activations.items(), ...)` 包含分数
  - `emgas_spreading.py:60-83` — `spread_activation()` 方法，返回 `dict[str, float]`（node_id → activation）

  **API/Type References**:
  - `memory_engine_emgas.py:80` — 唯一调用者 `self.graph.retrieve_context(seed_concepts=..., options=...)`

  **WHY Each Reference Matters**:
  - `retrieve_context` line 113 的 `ranked` 已有分数，只需保留而非丢弃
  - 确认只有 1 个调用者，返回类型变更安全

  **Acceptance Criteria**:
  - [ ] `retrieve_context()` 返回 `dict[str, float]`
  - [ ] 所有返回的 score 值在 `0.0 <= score <= 1.0` 范围内
  - [ ] 单节点场景：返回 `{passage_id: 1.0}`
  - [ ] 全等激活场景：所有 score == 1.0

  **QA Scenarios**:

  ```
  Scenario: 返回类型验证
    Tool: Bash (python)
    Preconditions: emgas_spreading.py 已修改
    Steps:
      1. 创建 EMGASGraph，添加 2 条记忆，调用 retrieve_context
      2. 断言返回类型为 dict
      3. 断言所有 value 为 float 且 0.0 <= v <= 1.0
    Expected Result: dict[str, float]，所有值在 [0, 1]
    Failure Indicators: 返回 set 或值超出范围
    Evidence: .sisyphus/evidence/task-2-return-type.txt

  Scenario: 全等激活除零保护
    Tool: Bash (python)
    Preconditions: 同上
    Steps:
      1. 创建只有 1 个 passage 的图
      2. 调用 retrieve_context
      3. 断言返回的 score == 1.0
    Expected Result: {passage_id: 1.0}
    Failure Indicators: 除零异常或 score 为 NaN/0
    Evidence: .sisyphus/evidence/task-2-single-node.txt
  ```

  **Commit**: YES
  - Message: `feat(emgas): return activation scores from retrieve_context`
  - Files: `emgas_spreading.py`
  - Pre-commit: `python -c "from emgas_spreading import EMGASGraph; print('OK')"`

- [ ] 3. EMGAS `search_memory` 注入归一化 score 字段

  **What to do**:
  - 修改 `memory_engine_emgas.py` 中 `EMGASEngine.search_memory()` 方法（line 66-93）
  - `retrieve_context()` 现在返回 `dict[str, float]`（Task 2 完成后），遍历时将激活分数注入到每个结果 dict 的 `"score"` 字段
  - 对于 `passage_store` 中找不到的 passage（line 92 的 fallback），也注入对应的 score
  - 确保所有返回结果都包含 `"score"` 键

  **Must NOT do**:
  - 不修改 `add_memory`/`remove_memory`
  - 不修改 `passage_store` 的持久化内容（score 是查询时计算的，不存储）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单文件小改动，逻辑直接
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 7
  - **Blocked By**: Task 2

  **References**:

  **Pattern References**:
  - `memory_engine_emgas.py:66-93` — 当前 `search_memory()` 实现，遍历 `passage_ids` 构建结果
  - `memory_engine_hippo.py:118` — HippoEngine 注入 score 的模式：`"score": hybrid_score`

  **API/Type References**:
  - `emgas_spreading.py::retrieve_context()` — Task 2 修改后返回 `dict[str, float]`

  **WHY Each Reference Matters**:
  - HippoEngine 的模式是参考范例，EMGAS 应遵循相同的 score 注入方式
  - `retrieve_context` 的新返回类型决定了如何获取每个 passage 的分数

  **Acceptance Criteria**:
  - [ ] `EMGASEngine.search_memory("query")` 返回的每个 dict 都包含 `"score"` 键
  - [ ] 所有 score 值在 `0.0 <= score <= 1.0`
  - [ ] 无结果时返回空列表（不崩溃）

  **QA Scenarios**:

  ```
  Scenario: EMGAS 结果包含 score 字段
    Tool: Bash (python)
    Preconditions: memory_engine_emgas.py 已修改，emgas_spreading.py 已修改
    Steps:
      1. 创建 EMGASEngine 实例，添加测试记忆
      2. 调用 search_memory("测试查询")
      3. 断言每个结果 dict 都有 "score" 键
      4. 断言所有 score 在 [0.0, 1.0]
    Expected Result: 所有结果含有效 score
    Failure Indicators: KeyError 或 score 超出范围
    Evidence: .sisyphus/evidence/task-3-emgas-score.txt

  Scenario: 空查询不崩溃
    Tool: Bash (python)
    Preconditions: 同上
    Steps:
      1. 调用 search_memory("")
      2. 断言返回 []
    Expected Result: 空列表
    Failure Indicators: 异常
    Evidence: .sisyphus/evidence/task-3-empty-query.txt
  ```

  **Commit**: YES
  - Message: `fix(emgas): inject normalized score field in search results`
  - Files: `memory_engine_emgas.py`
  - Pre-commit: `python -c "from memory_engine_emgas import EMGASEngine; print('OK')"`

- [ ] 4. `plugin_method.py` 替换 3 处硬编码评分为统一函数

  **What to do**:
  - 删除 `plugin_method.py` 中 3 处内联定义的 `_get_combined_score`（line 758-766, line 1431-1439, line 1838-1846）
  - 在文件顶部 import 区域添加：从 `mem0_output_formatter` 导入 `_get_combined_score`
  - 3 处排序调用 `merged_results.sort(key=_get_combined_score, ...)` 改为传入 `importance_weight`：
    - line 768: `merged_results.sort(key=lambda item: _get_combined_score(item, importance_weight=plugin_config.IMPORTANCE_WEIGHT), reverse=True)`
    - line 1441: `merged_results.sort(key=lambda item: _get_combined_score(item, importance_weight=config.IMPORTANCE_WEIGHT), reverse=True)`
    - line 1848: `merged_results.sort(key=lambda item: _get_combined_score(item, importance_weight=plugin_config.IMPORTANCE_WEIGHT), reverse=True)`
  - 3 处 `format_search_output` 调用添加 `importance_weight` 参数：
    - line 771-773: 添加 `importance_weight=plugin_config.IMPORTANCE_WEIGHT`
    - line 1448-1450: 添加 `importance_weight=config.IMPORTANCE_WEIGHT`
    - line 1851-1853: 添加 `importance_weight=plugin_config.IMPORTANCE_WEIGHT`

  **Must NOT do**:
  - 不修改评分逻辑本身（已在 Task 1 统一）
  - 不触碰 `dedup_similarity.py`

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 机械替换，模式明确
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Task 3, 5)
  - **Blocks**: Task 6, 7
  - **Blocked By**: Task 1

  **References**:

  **Pattern References**:
  - `plugin_method.py:758-766` — 第 1 处硬编码（`search_memory` 函数内）
  - `plugin_method.py:1431-1439` — 第 2 处硬编码（`_execute_pre_search` 函数内）
  - `plugin_method.py:1838-1846` — 第 3 处硬编码（`_command_search` 函数内）
  - `plugin_method.py:23` — 现有 import 行 `from .mem0_output_formatter import normalize_results, format_search_output`

  **API/Type References**:
  - `mem0_output_formatter.py::_get_combined_score` — Task 1 统一后的函数签名
  - `plugin.py:86-90` — `IMPORTANCE_WEIGHT` 配置

  **WHY Each Reference Matters**:
  - 3 处硬编码位置必须精确定位并全部替换
  - 现有 import 行是添加新 import 的锚点

  **Acceptance Criteria**:
  - [ ] `grep -n "0\.7 \* score" plugin_method.py` 返回 0 匹配
  - [ ] `grep -n "def _get_combined_score" plugin_method.py` 返回 0 匹配
  - [ ] `grep -n "IMPORTANCE_WEIGHT" plugin_method.py` 返回 ≥ 3 匹配
  - [ ] 文件无语法错误：`python -c "import plugin_method; print('OK')"`

  **QA Scenarios**:

  ```
  Scenario: 硬编码完全消除
    Tool: Bash (grep)
    Preconditions: plugin_method.py 已修改
    Steps:
      1. grep -cn "0\.7 \* score" plugin_method.py
      2. grep -cn "def _get_combined_score" plugin_method.py
      3. 断言两者均为 0
    Expected Result: 0 匹配
    Failure Indicators: 任何匹配 > 0
    Evidence: .sisyphus/evidence/task-4-no-hardcode.txt

  Scenario: IMPORTANCE_WEIGHT 配置已接入
    Tool: Bash (grep)
    Preconditions: 同上
    Steps:
      1. grep -cn "IMPORTANCE_WEIGHT" plugin_method.py
      2. 断言 ≥ 3
    Expected Result: ≥ 3 匹配
    Failure Indicators: < 3
    Evidence: .sisyphus/evidence/task-4-config-wired.txt
  ```

  **Commit**: YES
  - Message: `refactor(search): replace hardcoded scoring with unified function`
  - Files: `plugin_method.py`
  - Pre-commit: `grep -c "def _get_combined_score" plugin_method.py | grep -q "^0$"`

- [ ] 5. 新增 `PRE_SEARCH_SCORE_THRESHOLD` 配置并接入 PreSearch

  **What to do**:
  - 在 `plugin.py` 的 `PluginConfig` 类中，在 `PRE_SEARCH_TIMEOUT` 之后添加新配置项：
    ```python
    PRE_SEARCH_SCORE_THRESHOLD: Optional[float] = Field(
        default=0.35,
        title="预搜索分数阈值",
        description="预搜索的最低组合分数阈值（None 表示使用 MEMORY_SEARCH_SCORE_THRESHOLD）。预搜索场景建议较低阈值以提高召回率",
    )
    ```
  - 在 `plugin_method.py` 的 `_execute_pre_search` 函数中（line ~1449），将 `config.MEMORY_SEARCH_SCORE_THRESHOLD` 替换为：
    ```python
    pre_search_threshold = config.PRE_SEARCH_SCORE_THRESHOLD
    if pre_search_threshold is None:
        pre_search_threshold = config.MEMORY_SEARCH_SCORE_THRESHOLD
    ```
  - 同时将 `MEMORY_SEARCH_SCORE_THRESHOLD` 的默认值从 `0.7` 降低到 `0.5`（更合理的通用默认值）

  **Must NOT do**:
  - 不修改 `search_memory` 和 `_command_search` 中的阈值逻辑（它们继续使用 `MEMORY_SEARCH_SCORE_THRESHOLD`）
  - 不删除 `MEMORY_SEARCH_SCORE_THRESHOLD` 配置

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 两个文件的小改动
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Task 3, 4)
  - **Blocks**: Task 6, 7
  - **Blocked By**: Task 1

  **References**:

  **Pattern References**:
  - `plugin.py:135-139` — `PRE_SEARCH_TIMEOUT` 配置定义（新配置应紧随其后）
  - `plugin.py:83-85` — `MEMORY_SEARCH_SCORE_THRESHOLD` 当前定义（需改默认值）

  **API/Type References**:
  - `plugin_method.py:1447-1450` — PreSearch 中使用阈值的位置

  **WHY Each Reference Matters**:
  - 新配置应放在其他 PRE_SEARCH_* 配置附近，保持组织一致性
  - 精确定位 PreSearch 中阈值使用点以替换

  **Acceptance Criteria**:
  - [ ] `plugin.py` 包含 `PRE_SEARCH_SCORE_THRESHOLD` 定义，默认 0.35
  - [ ] `plugin.py` 中 `MEMORY_SEARCH_SCORE_THRESHOLD` 默认值为 0.5
  - [ ] `plugin_method.py` 的 `_execute_pre_search` 使用 `PRE_SEARCH_SCORE_THRESHOLD`
  - [ ] `search_memory` 和 `_command_search` 仍使用 `MEMORY_SEARCH_SCORE_THRESHOLD`

  **QA Scenarios**:

  ```
  Scenario: PreSearch 使用独立阈值
    Tool: Bash (grep)
    Preconditions: plugin.py 和 plugin_method.py 已修改
    Steps:
      1. grep -n "PRE_SEARCH_SCORE_THRESHOLD" plugin.py
      2. grep -n "PRE_SEARCH_SCORE_THRESHOLD\|pre_search_threshold" plugin_method.py
      3. 断言 plugin.py 有定义，plugin_method.py 有使用
    Expected Result: 配置定义和使用均存在
    Failure Indicators: 任一文件缺少匹配
    Evidence: .sisyphus/evidence/task-5-independent-threshold.txt

  Scenario: 默认阈值已降低
    Tool: Bash (grep)
    Preconditions: 同上
    Steps:
      1. grep "MEMORY_SEARCH_SCORE_THRESHOLD.*default" plugin.py
      2. 断言默认值为 0.5
    Expected Result: default=0.5
    Failure Indicators: default 仍为 0.7
    Evidence: .sisyphus/evidence/task-5-lowered-default.txt
  ```

  **Commit**: YES
  - Message: `feat(config): add PRE_SEARCH_SCORE_THRESHOLD for independent presearch tuning`
  - Files: `plugin.py`, `plugin_method.py`
  - Pre-commit: `python -c "from plugin import PluginConfig; print('OK')"`

- [ ] 6. 回退日志降级 + 诊断日志

  **What to do**:
  - `plugin_method.py:1453`：将 `logger.info("[PreSearch] 阈值过滤后为空，回退为低阈值结果注入")` 改为 `logger.debug`
  - 在 `_execute_pre_search` 的阈值过滤前（line ~1447 之前），添加诊断日志：
    ```python
    if top_results:
        scores = [_get_combined_score(item, importance_weight=config.IMPORTANCE_WEIGHT) for item in top_results[:5]]
        logger.debug(f"[PreSearch] top-5 combined scores: {[f'{s:.3f}' for s in scores]}, threshold={pre_search_threshold}")
    ```
  - 这样在 debug 级别可以看到实际分数分布，便于后续调参

  **Must NOT do**:
  - 不删除回退日志（只降级）
  - 不添加 info 级别以上的新日志

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 两行改动
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 7
  - **Blocked By**: Task 4, 5

  **References**:

  **Pattern References**:
  - `plugin_method.py:1453` — 当前 `logger.info` 回退日志
  - `plugin_method.py:1441-1445` — 排序和截取 top_results 的位置（诊断日志应在此之后）

  **WHY Each Reference Matters**:
  - 精确定位需要降级的日志行
  - 诊断日志应在排序后、过滤前，才能看到实际进入过滤的分数

  **Acceptance Criteria**:
  - [ ] `grep -n 'logger.info.*阈值过滤后为空' plugin_method.py` 返回 0 匹配
  - [ ] `grep -n 'logger.debug.*阈值过滤后为空' plugin_method.py` 返回 1 匹配
  - [ ] `grep -n 'combined scores' plugin_method.py` 返回 1 匹配

  **QA Scenarios**:

  ```
  Scenario: 回退日志已降级
    Tool: Bash (grep)
    Preconditions: plugin_method.py 已修改
    Steps:
      1. grep -c 'logger.info.*阈值过滤后为空' plugin_method.py
      2. grep -c 'logger.debug.*阈值过滤后为空' plugin_method.py
      3. 断言 info 为 0，debug 为 1
    Expected Result: info=0, debug=1
    Failure Indicators: info > 0
    Evidence: .sisyphus/evidence/task-6-log-demoted.txt

  Scenario: 诊断日志已添加
    Tool: Bash (grep)
    Preconditions: 同上
    Steps:
      1. grep -c 'combined scores' plugin_method.py
      2. 断言 == 1
    Expected Result: 1 匹配
    Failure Indicators: 0 匹配
    Evidence: .sisyphus/evidence/task-6-diagnostic-log.txt
  ```

  **Commit**: YES
  - Message: `fix(logging): demote presearch fallback log to debug, add score diagnostics`
  - Files: `plugin_method.py`
  - Pre-commit: `python -c "import ast; ast.parse(open('plugin_method.py').read()); print('OK')"`

- [ ] 7. 更新测试 stub + 全量回归测试

  **What to do**:
  - 更新 `test_memory_scope_risks.py` 中 `_DummyPluginConfig`（line ~55-66）：
    - 添加 `IMPORTANCE_WEIGHT = 0.3`
    - 添加 `PRE_SEARCH_SCORE_THRESHOLD = 0.35`
  - 更新 `test_pre_search_falls_back_when_threshold_filters_all`（line 288-324）：
    - 验证 score=0.1 的结果在新阈值 0.35 下仍触发回退（因为 combined = 0.7*0.1 + 0.3*0.5 = 0.22 < 0.35）
  - 新增测试：`test_pre_search_passes_threshold_with_decent_score`
    - 验证 score=0.5, importance=5 的结果（combined = 0.7*0.5 + 0.3*0.5 = 0.5 > 0.35）不触发回退
  - 新增测试：`test_combined_score_uses_config_weight`
    - 验证 `_get_combined_score` 使用 `importance_weight` 参数
  - 运行全量测试：`python -m pytest test_memory_scope_risks.py -v`

  **Must NOT do**:
  - 不删除现有测试
  - 不修改测试之外的代码

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要理解测试框架和 mock 模式，编写多个新测试
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (after Task 6)
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 1-6

  **References**:

  **Pattern References**:
  - `test_memory_scope_risks.py:55-66` — `_DummyPluginConfig` 定义
  - `test_memory_scope_risks.py:288-324` — 现有回退测试
  - `test_memory_scope_risks.py:327-369` — conversation 回退测试（参考 mock 模式）

  **API/Type References**:
  - `mem0_output_formatter.py::_get_combined_score` — 统一后的函数签名
  - `plugin.py::PluginConfig` — 新增的配置字段

  **WHY Each Reference Matters**:
  - `_DummyPluginConfig` 是所有 PreSearch 测试的配置 stub，必须包含新字段
  - 现有测试的 mock 模式是新测试的参考范例

  **Acceptance Criteria**:
  - [ ] `python -m pytest test_memory_scope_risks.py -v` 全部通过
  - [ ] 新增 ≥ 2 个测试函数
  - [ ] `_DummyPluginConfig` 包含 `IMPORTANCE_WEIGHT` 和 `PRE_SEARCH_SCORE_THRESHOLD`

  **QA Scenarios**:

  ```
  Scenario: 全量测试通过
    Tool: Bash (pytest)
    Preconditions: 所有 Task 1-6 已完成
    Steps:
      1. python -m pytest test_memory_scope_risks.py -v
      2. 断言所有测试 PASSED
    Expected Result: 0 failures
    Failure Indicators: 任何 FAILED
    Evidence: .sisyphus/evidence/task-7-full-test.txt

  Scenario: 新测试存在且通过
    Tool: Bash (grep + pytest)
    Preconditions: 同上
    Steps:
      1. grep -c "def test_pre_search_passes_threshold\|def test_combined_score_uses_config" test_memory_scope_risks.py
      2. 断言 ≥ 2
    Expected Result: ≥ 2 新测试函数
    Failure Indicators: < 2
    Evidence: .sisyphus/evidence/task-7-new-tests.txt
  ```

  **Commit**: YES
  - Message: `test(presearch): update stubs and add regression tests for threshold fix`
  - Files: `test_memory_scope_risks.py`
  - Pre-commit: `python -m pytest test_memory_scope_risks.py -v`

---

## Final Verification Wave

> 4 review agents run in PARALLEL. ALL must APPROVE. Rejection → fix → re-run.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run linter + `python -m pytest test_memory_scope_risks.py -v`. Review all changed files for: `as any`/type ignores, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names.
  Output: `Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Commit 1**: `fix(scoring): unify _get_combined_score with configurable importance_weight` — mem0_output_formatter.py
- **Commit 2**: `feat(emgas): return activation scores from retrieve_context` — emgas_spreading.py
- **Commit 3**: `fix(emgas): inject normalized score field in search results` — memory_engine_emgas.py
- **Commit 4**: `refactor(search): replace hardcoded scoring with unified function` — plugin_method.py
- **Commit 5**: `feat(config): add PRE_SEARCH_SCORE_THRESHOLD for independent presearch tuning` — plugin.py, plugin_method.py
- **Commit 6**: `fix(logging): demote presearch fallback log to debug, add score diagnostics` — plugin_method.py
- **Commit 7**: `test(presearch): update stubs and add regression tests for threshold fix` — test_memory_scope_risks.py

---

## Success Criteria

### Verification Commands
```bash
grep -rn "0\.7 \* score" *.py | grep -v dedup_similarity  # Expected: 0 matches
grep -rn "IMPORTANCE_WEIGHT" *.py  # Expected: ≥ 3 matches
python -m pytest test_memory_scope_risks.py -v  # Expected: all pass
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] EMGAS results contain valid score field
- [ ] PreSearch with default config does not trigger fallback on normal scores
