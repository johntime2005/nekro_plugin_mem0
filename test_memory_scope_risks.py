import importlib
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


if __name__ == "__main__":
    test_agent_scope_switch_disables_persona_layer()
    test_add_default_prefers_long_term_layer()
    test_persona_bind_user_requires_user_and_includes_user_id()
    print("✅ test_memory_scope_risks passed")
