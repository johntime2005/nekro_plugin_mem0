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
    setattr(output_stub, "format_add_output", lambda *args, **kwargs: "")
    setattr(output_stub, "format_get_all_output", lambda *args, **kwargs: {"text": ""})
    setattr(output_stub, "format_history_output", lambda *args, **kwargs: [])
    setattr(output_stub, "format_history_text", lambda *args, **kwargs: "")
    setattr(output_stub, "format_search_output", lambda *args, **kwargs: {"text": ""})
    setattr(output_stub, "normalize_results", lambda value: value or [])
    setattr(output_stub, "_format_memory_list", lambda *args, **kwargs: "")
    sys.modules[f"{package_name}.mem0_output_formatter"] = output_stub

    pre_search_stub = types.ModuleType(f"{package_name}.pre_search_utils")
    setattr(pre_search_stub, "build_pre_search_query", lambda *args, **kwargs: None)
    setattr(pre_search_stub, "convert_db_messages_to_dict", lambda *args, **kwargs: [])
    sys.modules[f"{package_name}.pre_search_utils"] = pre_search_stub

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


if __name__ == "__main__":
    test_agent_scope_switch_disables_persona_layer()
    test_add_default_prefers_long_term_layer()
    test_persona_bind_user_requires_user_and_includes_user_id()
    test_layer_query_kwargs_filters_none_values()
    test_read_layer_fallback_keeps_legacy_persona_readability()
    print("✅ test_memory_scope_risks passed")
