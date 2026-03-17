
## Task 7: Test Stub Updates & Regression Tests

### Key Findings
1. `_DummyPluginConfig` 需要与 `plugin_method.py` 中 `_execute_pre_search` 使用的所有 config 属性保持同步。缺少 `QUERY_REWRITE_ENABLED` 会导致 `_execute_pre_search` 静默捕获异常并返回 None。
2. `_load_plugin_method_module()` 返回缓存的模块对象。`setattr` 修改会污染后续测试。需要在测试后恢复原始值。
3. stub 中的 `format_search_output` 需要同步更新以使用 `_get_combined_score`，否则阈值过滤逻辑不一致。
4. pytest 无法直接运行测试，因为 `__init__.py` 导入了 `nekro_agent`。测试通过 `python test_memory_scope_risks.py` 直接运行。
5. `test_inject_memory_prompt_returns_base_when_pre_search_empty` 的断言 "你可以使用记忆插件" 已过时，更新为 "长期记忆插件"。

### Additional Config Fields Added
- `QUERY_REWRITE_ENABLED = False`
- `LEGACY_SCOPE_FALLBACK_ENABLED = True`
- `AUTO_MIGRATE_ON_READ = False`
- `AUTO_EXTRACT_ENABLED = False`
- `AUTO_EXTRACT_INTERVAL = 3`
- `AUTO_EXTRACT_TARGET_LAYER = "persona"`
- `DEDUP_ENABLED = False`
