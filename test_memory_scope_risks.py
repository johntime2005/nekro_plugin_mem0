import importlib
import os
import sys
import types


def _install_nekro_stubs() -> None:
    if "nekro_agent.api.schemas" in sys.modules:
        return

    class _DummyLogger:
        def debug(self, *args, **kwargs):
            return None

        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

    api_schemas = types.ModuleType("nekro_agent.api.schemas")
    setattr(api_schemas, "AgentCtx", object)

    core_mod = types.ModuleType("nekro_agent.core")
    setattr(core_mod, "logger", _DummyLogger())

    core_config_mod = types.ModuleType("nekro_agent.core.config")
    setattr(core_config_mod, "ModelConfigGroup", object)
    setattr(core_config_mod, "config", types.SimpleNamespace(MODEL_GROUPS={}))

    sys.modules["nekro_agent"] = types.ModuleType("nekro_agent")
    sys.modules["nekro_agent.api"] = types.ModuleType("nekro_agent.api")
    sys.modules["nekro_agent.api.schemas"] = api_schemas
    sys.modules["nekro_agent.core"] = core_mod
    sys.modules["nekro_agent.core.config"] = core_config_mod


def _load_memory_scope_class():
    _install_nekro_stubs()
    module = importlib.import_module("utils")
    return module.MemoryScope


def _load_plugin_method_module():
    _install_nekro_stubs()

    package_name = "nekro_plugin_mem0"
    package_root = os.path.dirname(os.path.abspath(__file__))
    package_mod = types.ModuleType(package_name)
    package_mod.__path__ = [package_root]
    sys.modules[package_name] = package_mod

    plugin_stub = types.ModuleType(f"{package_name}.plugin")

    class _DummyPluginConfig:
        ENABLE_AGENT_SCOPE = True
        PERSONA_BIND_USER = True
        PRE_SEARCH_DB_MESSAGE_COUNT = 50
        PRE_SEARCH_QUERY_MESSAGE_COUNT = 10
        PRE_SEARCH_QUERY_MAX_LENGTH = 500
        PRE_SEARCH_SKIP_CONVERSATION = True
        PRE_SEARCH_RESULT_LIMIT = 5
        PRE_SEARCH_TIMEOUT = 0.8
        MEMORY_SEARCH_SCORE_THRESHOLD = 0.7
        SESSION_ISOLATION = True
        PRE_SEARCH_ENABLED = True
        IMPORTANCE_WEIGHT = 0.3
        PRE_SEARCH_SCORE_THRESHOLD = 0.35
        QUERY_REWRITE_ENABLED = False
        LEGACY_SCOPE_FALLBACK_ENABLED = True
        AUTO_MIGRATE_ON_READ = False
        AUTO_EXTRACT_ENABLED = False
        AUTO_EXTRACT_INTERVAL = 3
        AUTO_EXTRACT_TARGET_LAYER = "persona"
        DEDUP_ENABLED = False

    class _DummyPlugin:
        def mount_init_method(self):
            def _decorator(func):
                return func

            return _decorator

        def mount_sandbox_method(self, *args, **kwargs):
            def _decorator(func):
                return func

            return _decorator

        def mount_prompt_inject_method(self, *args, **kwargs):
            def _decorator(func):
                return func

            return _decorator

        def mount_command_group(self, *args, **kwargs):
            class _DummyGroup:
                def command(self, *c_args, **c_kwargs):
                    def _decorator(func):
                        return func

                    return _decorator

            return _DummyGroup()

    setattr(plugin_stub, "plugin", _DummyPlugin())
    setattr(plugin_stub, "get_memory_config", lambda: _DummyPluginConfig())
    sys.modules[f"{package_name}.plugin"] = plugin_stub

    mem0_utils_stub = types.ModuleType(f"{package_name}.mem0_utils")

    async def _dummy_get_mem0_client():
        return None

    setattr(mem0_utils_stub, "get_mem0_client", _dummy_get_mem0_client)
    sys.modules[f"{package_name}.mem0_utils"] = mem0_utils_stub

    output_stub = types.ModuleType(f"{package_name}.mem0_output_formatter")

    def _normalize_results(value):
        if isinstance(value, dict):
            return value.get("results", [])
        return value or []

    def _format_memory_list(items):
        if not items:
            return "(无结果)"
        lines = []
        for item in items:
            text = item.get("memory") or item.get("data") or item.get("content") or ""
            if text:
                lines.append(f"- {text}")
        return "\n".join(lines) if lines else "(无结果)"

    def _get_combined_score(item, importance_weight=0.3):
        score = item.get("score") or 0.0
        if not isinstance(score, (int, float)):
            score = 0.0
        metadata = item.get("metadata") or {}
        importance = metadata.get("importance", 5)
        try:
            importance = max(1, min(10, int(importance)))
        except (ValueError, TypeError):
            importance = 5
        w = max(0.0, min(1.0, float(importance_weight)))
        return (1.0 - w) * float(score) + w * (importance / 10.0)

    def _format_search_output(
        results, tags=None, threshold=None, importance_weight=0.3
    ):
        filtered = _normalize_results(results)
        if threshold is not None:
            filtered = [
                item
                for item in filtered
                if _get_combined_score(item, importance_weight=importance_weight)
                >= threshold
            ]
        return {"results": filtered, "text": _format_memory_list(filtered)}

    setattr(output_stub, "format_add_output", lambda *args, **kwargs: "")
    setattr(
        output_stub,
        "format_get_all_output",
        lambda results, *args, **kwargs: {
            "results": _normalize_results(results),
            "text": _format_memory_list(_normalize_results(results)),
        },
    )
    setattr(output_stub, "format_history_output", lambda *args, **kwargs: [])
    setattr(output_stub, "format_history_text", lambda *args, **kwargs: "")
    setattr(output_stub, "format_search_output", _format_search_output)
    setattr(output_stub, "normalize_results", _normalize_results)
    setattr(output_stub, "_format_memory_list", _format_memory_list)
    setattr(output_stub, "_get_combined_score", _get_combined_score)
    sys.modules[f"{package_name}.mem0_output_formatter"] = output_stub

    pre_search_stub = types.ModuleType(f"{package_name}.pre_search_utils")
    setattr(pre_search_stub, "build_pre_search_query", lambda *args, **kwargs: None)
    setattr(pre_search_stub, "convert_db_messages_to_dict", lambda *args, **kwargs: [])
    sys.modules[f"{package_name}.pre_search_utils"] = pre_search_stub

    extraction_parser_stub = types.ModuleType(f"{package_name}.extraction_parser")
    setattr(extraction_parser_stub, "parse_extracted_memories", lambda *args, **kwargs: [])
    sys.modules[f"{package_name}.extraction_parser"] = extraction_parser_stub

    extraction_prompts_stub = types.ModuleType(f"{package_name}.extraction_prompts")
    setattr(extraction_prompts_stub, "ENHANCED_MEMORY_PROMPT", "")
    sys.modules[f"{package_name}.extraction_prompts"] = extraction_prompts_stub

    query_rewrite_stub = types.ModuleType(f"{package_name}.query_rewrite")
    setattr(query_rewrite_stub, "should_skip_retrieval", lambda *args, **kwargs: False)
    sys.modules[f"{package_name}.query_rewrite"] = query_rewrite_stub

    memory_router_stub = types.ModuleType(f"{package_name}.memory_engine_router")

    async def _route_search_stub(*args, **kwargs):
        return []

    setattr(memory_router_stub, "route_search", _route_search_stub)
    sys.modules[f"{package_name}.memory_engine_router"] = memory_router_stub

    utils_module = importlib.import_module("utils")
    sys.modules[f"{package_name}.utils"] = utils_module

    cmd_base_mod = types.ModuleType("nekro_agent.services.command.base")

    class _DummyCommandPermission:
        PUBLIC = "public"
        ADVANCED = "advanced"
        SUPER_USER = "super_user"

    setattr(cmd_base_mod, "CommandPermission", _DummyCommandPermission)

    class _DummyCmdCtl:
        @staticmethod
        def success(text):
            return text

        @staticmethod
        def failed(text):
            return text

    cmd_ctl_mod = types.ModuleType("nekro_agent.services.command.ctl")
    setattr(cmd_ctl_mod, "CmdCtl", _DummyCmdCtl)

    cmd_schemas_mod = types.ModuleType("nekro_agent.services.command.schemas")
    setattr(cmd_schemas_mod, "Arg", lambda *args, **kwargs: str)
    setattr(cmd_schemas_mod, "CommandExecutionContext", object)
    setattr(cmd_schemas_mod, "CommandResponse", object)

    plugin_base_mod = types.ModuleType("nekro_agent.services.plugin.base")

    class _DummySandboxMethodType:
        BEHAVIOR = "behavior"
        AGENT = "agent"

    setattr(plugin_base_mod, "SandboxMethodType", _DummySandboxMethodType)

    db_chat_mod = types.ModuleType("nekro_agent.models.db_chat_message")
    setattr(db_chat_mod, "DBChatMessage", object)

    sys.modules["nekro_agent.services.command.base"] = cmd_base_mod
    sys.modules["nekro_agent.services.command.ctl"] = cmd_ctl_mod
    sys.modules["nekro_agent.services.command.schemas"] = cmd_schemas_mod
    sys.modules["nekro_agent.services.plugin.base"] = plugin_base_mod
    sys.modules["nekro_agent.models.db_chat_message"] = db_chat_mod

    module = importlib.import_module(f"{package_name}.plugin_method")
    return module


def test_agent_scope_switch_disables_persona_layer() -> None:
    MemoryScope = _load_memory_scope_class()
    scope = MemoryScope(user_id="u1", agent_id="a1", run_id="r1")

    assert scope.layer_ids("persona", enable_agent_layer=False) is None
    assert scope.default_layer_order(
        enable_session_layer=True,
        enable_agent_layer=False,
    ) == ["conversation", "global"]


def test_add_default_prefers_long_term_layer() -> None:
    MemoryScope = _load_memory_scope_class()
    scope = MemoryScope(user_id="u1", agent_id="a1", run_id="r1")

    picked = scope.pick_layer(
        preferred=None,
        enable_session_layer=True,
        enable_agent_layer=True,
        prefer_long_term=True,
    )
    assert picked == "persona"


def test_persona_bind_user_requires_user_and_includes_user_id() -> None:
    MemoryScope = _load_memory_scope_class()

    scope_no_user = MemoryScope(user_id=None, agent_id="a1", run_id="r1")
    assert (
        scope_no_user.layer_ids(
            "persona",
            enable_agent_layer=True,
            bind_persona_to_user=True,
        )
        is None
    )

    scope = MemoryScope(user_id="u1", agent_id="a1", run_id="r1")
    persona = scope.layer_ids(
        "persona",
        enable_agent_layer=True,
        bind_persona_to_user=True,
    )
    assert persona == {
        "layer": "persona",
        "user_id": "u1",
        "agent_id": "a1",
        "run_id": None,
    }


def test_layer_query_kwargs_filters_none_values() -> None:
    plugin_method = _load_plugin_method_module()

    kwargs = plugin_method._layer_query_kwargs(
        {
            "layer": "persona",
            "user_id": None,
            "agent_id": "a1",
            "run_id": None,
        },
        plugin_config=object(),
    )

    assert kwargs == {"agent_id": "a1"}


def test_read_layer_fallback_keeps_legacy_persona_readability() -> None:
    MemoryScope = _load_memory_scope_class()
    plugin_method = _load_plugin_method_module()

    scope = MemoryScope(user_id=None, agent_id="a1", run_id="r1")
    config = types.SimpleNamespace(ENABLE_AGENT_SCOPE=True, PERSONA_BIND_USER=True)

    layer_ids = plugin_method._resolve_read_layer_ids(scope, "persona", config)

    assert layer_ids == {
        "layer": "persona",
        "user_id": None,
        "agent_id": "a1",
        "run_id": None,
    }


def test_pre_search_falls_back_when_threshold_filters_all() -> None:
    plugin_method = _load_plugin_method_module()

    class _Ctx:
        chat_key = "chat_1"

    async def _fake_fetch_recent_messages(_ctx, _count):
        return [{"role": "user", "content": "今天可真是冷啊"}]

    async def _fake_search_single_layer(_client, _query, layer_ids, _limit, _config):
        return (
            layer_ids["layer"],
            [
                {
                    "id": "mem_1",
                    "memory": "用户怕冷，天气冷时希望被提醒添衣",
                    "score": 0.1,
                }
            ],
        )

    async def _fake_get_mem0_client():
        return object()

    setattr(plugin_method, "_fetch_recent_messages", _fake_fetch_recent_messages)
    setattr(
        plugin_method,
        "build_pre_search_query",
        lambda *args, **kwargs: "今天可真是冷啊",
    )
    setattr(plugin_method, "_search_single_layer", _fake_search_single_layer)
    setattr(plugin_method, "get_mem0_client", _fake_get_mem0_client)

    result = __import__("asyncio").run(plugin_method._execute_pre_search(_Ctx()))

    assert result is not None
    assert "用户怕冷" in result


def test_pre_search_second_pass_conversation_fallback_when_first_pass_empty() -> None:
    plugin_method = _load_plugin_method_module()

    class _Ctx:
        chat_key = "chat_2"

    async def _fake_fetch_recent_messages(_ctx, _count):
        return [{"role": "user", "content": "今天可真是冷啊"}]

    async def _fake_get_mem0_client():
        return object()

    call_layers = []

    async def _fake_search_single_layer(_client, _query, layer_ids, _limit, _config):
        call_layers.append(layer_ids["layer"])
        if layer_ids["layer"] == "conversation":
            return (
                "conversation",
                [
                    {
                        "id": "mem_conv_1",
                        "memory": "当前会话提到天气寒冷",
                        "score": 0.9,
                    }
                ],
            )
        return (layer_ids["layer"], [])

    setattr(plugin_method, "_fetch_recent_messages", _fake_fetch_recent_messages)
    setattr(
        plugin_method,
        "build_pre_search_query",
        lambda *args, **kwargs: "今天可真是冷啊",
    )
    setattr(plugin_method, "_search_single_layer", _fake_search_single_layer)
    setattr(plugin_method, "get_mem0_client", _fake_get_mem0_client)

    result = __import__("asyncio").run(plugin_method._execute_pre_search(_Ctx()))

    assert result is not None
    assert "当前会话提到天气寒冷" in result
    assert "conversation" in call_layers


def test_pre_search_passes_threshold_with_decent_score() -> None:
    plugin_method = _load_plugin_method_module()

    class _Ctx:
        chat_key = "chat_decent"

    async def _fake_fetch_recent_messages(_ctx, _count):
        return [{"role": "user", "content": "用户喜欢喝茶"}]

    async def _fake_search_single_layer(_client, _query, layer_ids, _limit, _config):
        # score=0.5, importance=5 → combined = 0.7*0.5 + 0.3*0.5 = 0.5 > 0.35
        return (
            layer_ids["layer"],
            [
                {
                    "id": "mem_decent",
                    "memory": "用户喜欢喝茶",
                    "score": 0.5,
                    "metadata": {"importance": 5},
                }
            ],
        )

    async def _fake_get_mem0_client():
        return object()

    setattr(plugin_method, "_fetch_recent_messages", _fake_fetch_recent_messages)
    setattr(
        plugin_method,
        "build_pre_search_query",
        lambda *args, **kwargs: "用户喜欢喝茶",
    )
    setattr(plugin_method, "_search_single_layer", _fake_search_single_layer)
    setattr(plugin_method, "get_mem0_client", _fake_get_mem0_client)

    result = __import__("asyncio").run(plugin_method._execute_pre_search(_Ctx()))

    assert result is not None
    assert "用户喜欢喝茶" in result


def test_inject_memory_prompt_returns_base_when_pre_search_empty() -> None:
    plugin_method = _load_plugin_method_module()

    class _Ctx:
        chat_key = "chat_3"

    original_execute_pre_search = plugin_method._execute_pre_search

    async def _fake_execute_pre_search(_ctx):
        return None

    setattr(plugin_method, "_execute_pre_search", _fake_execute_pre_search)

    output = __import__("asyncio").run(plugin_method.inject_memory_prompt(_Ctx()))

    setattr(plugin_method, "_execute_pre_search", original_execute_pre_search)

    assert "📚 【预加载记忆】" not in output
    assert "长期记忆插件" in output


def test_pre_search_skip_reason_no_messages() -> None:
    plugin_method = _load_plugin_method_module()

    class _Ctx:
        chat_key = "chat_4"

    async def _fake_fetch_recent_messages(_ctx, _count):
        return []

    setattr(plugin_method, "_fetch_recent_messages", _fake_fetch_recent_messages)

    result = __import__("asyncio").run(plugin_method._execute_pre_search(_Ctx()))

    assert result is None


def test_combined_score_uses_config_weight() -> None:
    plugin_method = _load_plugin_method_module()
    _get_combined_score = getattr(
        sys.modules["nekro_plugin_mem0.mem0_output_formatter"], "_get_combined_score"
    )

    item = {"score": 0.8, "metadata": {"importance": 5}}
    # (1-0.5)*0.8 + 0.5*(5/10) = 0.4 + 0.25 = 0.65
    result = _get_combined_score(item, importance_weight=0.5)
    assert result == 0.65


def test_normalize_memory_metadata_sets_default_importance_and_expiration() -> None:
    plugin_method = _load_plugin_method_module()

    normalized = plugin_method._normalize_memory_metadata(
        {"TYPE": "FACTS"}, expiration_date="2026-12-31T00:00:00Z"
    )

    assert normalized["TYPE"] == "FACTS"
    assert normalized["expiration_date"] == "2026-12-31T00:00:00Z"
    assert normalized["importance"] == 5


def test_parse_metadata_normalizes_importance_value() -> None:
    plugin_method = _load_plugin_method_module()

    metadata = plugin_method._parse_metadata({"importance": "99"})

    assert metadata["importance"] == 5


def test_scan_records_from_registered_scopes_uses_scoped_get_all() -> None:
    plugin_method = _load_plugin_method_module()

    plugin_method._REGISTERED_SCOPE_QUERIES.clear()
    plugin_method._register_scope_query(user_id="u1")
    plugin_method._register_scope_query(agent_id="a1")

    class _Client:
        def __init__(self):
            self.calls = []

        def get_all(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("user_id") == "u1":
                return [{"id": "m1", "memory": "u1-memory"}]
            if kwargs.get("agent_id") == "a1":
                return [{"id": "m2", "memory": "a1-memory"}]
            return []

    client = _Client()
    records = __import__("asyncio").run(plugin_method._scan_records_from_registered_scopes(client))

    assert len(client.calls) == 2
    assert {tuple(sorted(c.items())) for c in client.calls} == {
        (("user_id", "u1"),),
        (("agent_id", "a1"),),
    }
    assert len(records) == 2
    assert {item["id"] for item in records} == {"m1", "m2"}


def test_cleanup_expired_memories_does_not_call_unscoped_get_all() -> None:
    plugin_method = _load_plugin_method_module()

    class _Client:
        def __init__(self):
            self.get_all_calls = []
            self.deleted = []

        def get_all(self, **kwargs):
            self.get_all_calls.append(kwargs)
            return [
                {
                    "id": "expired-1",
                    "metadata": {"expiration_date": "2000-01-01T00:00:00Z"},
                }
            ]

        def delete(self, memory_id):
            self.deleted.append(memory_id)

    async def _fake_get_mem0_client():
        return client

    client = _Client()
    plugin_method._REGISTERED_SCOPE_QUERIES.clear()
    plugin_method._register_scope_query(user_id="u-clean")
    setattr(plugin_method, "get_mem0_client", _fake_get_mem0_client)

    __import__("asyncio").run(plugin_method._cleanup_expired_memories())

    assert client.get_all_calls == [{"user_id": "u-clean"}]
    assert client.deleted == ["expired-1"]


def test_register_scope_context_does_not_register_persona_read_fallback() -> None:
    plugin_method = _load_plugin_method_module()
    MemoryScope = _load_memory_scope_class()

    plugin_method._REGISTERED_SCOPE_QUERIES.clear()
    scope = MemoryScope(user_id=None, agent_id="a-fallback", run_id="r-fallback")
    config = types.SimpleNamespace(
        ENABLE_AGENT_SCOPE=True,
        PERSONA_BIND_USER=True,
        ENABLE_GUILD_SCOPE=False,
    )

    plugin_method._register_scope_context(scope, config)

    assert (None, "a-fallback", None) not in plugin_method._REGISTERED_SCOPE_QUERIES
    assert (None, None, "r-fallback") in plugin_method._REGISTERED_SCOPE_QUERIES


if __name__ == "__main__":
    test_agent_scope_switch_disables_persona_layer()
    test_add_default_prefers_long_term_layer()
    test_persona_bind_user_requires_user_and_includes_user_id()
    test_layer_query_kwargs_filters_none_values()
    test_read_layer_fallback_keeps_legacy_persona_readability()
    test_pre_search_falls_back_when_threshold_filters_all()
    test_pre_search_second_pass_conversation_fallback_when_first_pass_empty()
    test_inject_memory_prompt_returns_base_when_pre_search_empty()
    test_pre_search_skip_reason_no_messages()
    test_pre_search_passes_threshold_with_decent_score()
    test_combined_score_uses_config_weight()
    test_normalize_memory_metadata_sets_default_importance_and_expiration()
    test_parse_metadata_normalizes_importance_value()
    test_scan_records_from_registered_scopes_uses_scoped_get_all()
    test_cleanup_expired_memories_does_not_call_unscoped_get_all()
    test_register_scope_context_does_not_register_persona_read_fallback()
    print("✅ test_memory_scope_risks passed")
