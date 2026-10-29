from pathlib import Path
from types import SimpleNamespace

import pytest

import runner.plugins.registry as registry
from runner.errors import RunnerError


@pytest.fixture(autouse=True)
def clear_plugin_registry_caches():
    registry.plugin_modules.cache_clear()
    registry.discover_plugins.cache_clear()
    yield
    registry.plugin_modules.cache_clear()
    registry.discover_plugins.cache_clear()


def test_plugin_modules_load_builtins_and_external_entrypoints_in_name_order(monkeypatch):
    built_a = SimpleNamespace(__name__="builtin.a")
    built_b = SimpleNamespace(__name__="builtin.b")
    loaded = []

    def fake_import(name):
        loaded.append(name)
        return {"builtin.a": built_a, "builtin.b": built_b}[name]

    ext_a = SimpleNamespace(PLUGIN_NAME="ext-a")
    ext_z = SimpleNamespace(PLUGIN_NAME="ext-z")

    class Point:
        def __init__(self, name, module):
            self.name = name
            self.module = module

        def load(self):
            loaded.append("entry:" + self.name)
            return self.module

    class Points:
        def select(self, *, group):
            assert group == registry.PLUGIN_ENTRYPOINT_GROUP
            return [Point("z-last", ext_z), Point("a-first", ext_a)]

    monkeypatch.setattr(registry, "BUILTIN_PLUGINS", ("builtin.a", "builtin.b"))
    monkeypatch.setattr(registry.importlib, "import_module", fake_import)
    monkeypatch.setattr(registry, "entry_points", lambda: Points())

    modules = registry.plugin_modules()

    assert modules == (built_a, built_b, ext_a, ext_z)
    assert loaded == [
        "builtin.a",
        "builtin.b",
        "entry:a-first",
        "entry:z-last",
    ]
    assert registry.plugin_modules() is modules


def test_plugin_modules_wrap_discovery_failure(monkeypatch):
    monkeypatch.setattr(registry, "BUILTIN_PLUGINS", ())
    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda: (_ for _ in ()).throw(RuntimeError("entrypoint failure")),
    )

    with pytest.raises(RunnerError, match="plugin discovery failed: entrypoint failure"):
        registry.plugin_modules()


def test_discover_register_and_add_arguments_call_plugin_hooks_once(monkeypatch):
    calls = []

    first = SimpleNamespace(
        PLUGIN_NAME="first",
        setup=lambda: calls.append("first-setup"),
        register=lambda runtime: calls.append(("first-register", runtime)),
        add_arguments=lambda parser: calls.append(("first-args", parser)),
    )
    second = SimpleNamespace(
        __name__="second.module",
        setup=lambda: calls.append("second-setup"),
    )
    monkeypatch.setattr(registry, "plugin_modules", lambda: (first, second))

    runtime = object()
    parser = object()

    assert registry.discover_plugins() == ("first", "second.module")
    assert registry.discover_plugins() == ("first", "second.module")
    registry.register_plugins(runtime)
    registry.add_plugin_arguments(parser)

    assert calls == [
        "first-setup",
        "second-setup",
        ("first-register", runtime),
        ("first-args", parser),
    ]


def test_plugin_config_collectors_yaml_fields_merge_and_normalize(monkeypatch):
    plugin = SimpleNamespace(
        PLUGIN_NAME="demo",
        YAML_FIELDS={"demo_enabled", "demo_threshold"},
        config_from_namespace=lambda ns: {"enabled": ns.enabled},
        config_from_request=lambda request: {"threshold": request.threshold},
        config_from_yaml=lambda item: (
            {"enabled": item["demo_enabled"]}
            if "demo_enabled" in item
            else {}
        ),
        normalize_config=lambda values: {
            "enabled": bool(values.get("enabled", False)),
            "threshold": int(values.get("threshold", 10)),
        },
    )
    plain = SimpleNamespace(PLUGIN_NAME="plain", YAML_FIELDS={"plain_flag"})
    monkeypatch.setattr(registry, "plugin_modules", lambda: (plugin, plain))
    monkeypatch.setattr(registry, "discover_plugins", lambda: ("demo", "plain"))

    assert registry.plugin_config_from_namespace(
        SimpleNamespace(enabled=True)
    ) == {"demo": {"enabled": True}}
    assert registry.plugin_config_from_request(
        SimpleNamespace(threshold=42)
    ) == {"demo": {"threshold": 42}}
    assert registry.plugin_config_from_yaml(
        {"demo_enabled": False}
    ) == {"demo": {"enabled": False}}
    assert registry.plugin_yaml_fields() == frozenset(
        {"demo_enabled", "demo_threshold", "plain_flag"}
    )

    assert registry.merge_plugin_config(
        {"demo": {"enabled": False, "threshold": 10}},
        {"demo": {"threshold": 25}, "plain": {"x": 1}},
    ) == {
        "demo": {"enabled": False, "threshold": 25},
        "plain": {"x": 1},
    }
    assert registry.normalize_plugin_config(
        {"demo": {"enabled": 1, "threshold": 7}, "plain": {"x": 1}}
    ) == {
        "demo": {"enabled": True, "threshold": 7},
        "plain": {"x": 1},
    }

    with pytest.raises(ValueError, match="unknown plugins: missing"):
        registry.normalize_plugin_config({"missing": {}})
    with pytest.raises(ValueError, match="plugins must be an object"):
        registry.merge_plugin_config([], {})
    with pytest.raises(ValueError, match="each plugin configuration must be an object"):
        registry.merge_plugin_config({"demo": 1}, {})


def test_collect_plugin_instructions_uses_runtime_hook_and_is_safe_without_runtime(
    tmp_path: Path, monkeypatch
):
    calls = []

    class Hooks:
        def instructions(self, root):
            calls.append(root)
            return "plugin instruction"

    monkeypatch.setattr(
        "runner.bootstrap.current_runtime",
        lambda: SimpleNamespace(hooks=Hooks()),
    )
    assert registry.collect_plugin_instructions(tmp_path) == "plugin instruction"
    assert calls == [tmp_path]

    monkeypatch.setattr(
        "runner.bootstrap.current_runtime",
        lambda: (_ for _ in ()).throw(RuntimeError("no runtime")),
    )
    assert registry.collect_plugin_instructions(tmp_path) == ""
