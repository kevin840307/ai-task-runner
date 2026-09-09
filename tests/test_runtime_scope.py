import pytest

from runner.bootstrap import current_runtime, runtime_scope
from runner.config.runtime import RuntimeConfig
from runner.runtime import events


def test_nested_runtime_scope_restores_parent_runtime_and_events(tmp_path):
    outer_events = []
    inner_events = []
    outer_config = RuntimeConfig(project_root=str(tmp_path / "outer"), validator="ai", human_output=False)
    inner_config = RuntimeConfig(
        project_root=str(tmp_path / "inner"),
        validator="ai",
        human_output=False,
        script_index=2,
        script_total=3,
    )

    with runtime_scope(outer_config) as outer:
        outer.events.subscribe(outer_events.append)
        assert current_runtime() is outer
        events.publish("runner.test", "outer_before")

        with runtime_scope(inner_config) as inner:
            inner.events.subscribe(inner_events.append)
            assert current_runtime() is inner
            events.publish("runner.test", "inner")

        assert current_runtime() is outer
        events.publish("runner.test", "outer_after")

    with pytest.raises(RuntimeError):
        current_runtime()

    assert [event["action"] for event in outer_events] == ["outer_before", "outer_after"]
    assert [event["action"] for event in inner_events] == ["inner"]
    assert "script_index" not in outer_events[-1]
    assert inner_events[-1]["script_index"] == 2
    assert inner_events[-1]["script_total"] == 3


def test_bootstrap_has_single_scoped_runtime_entrypoint():
    import runner.bootstrap as bootstrap

    assert not hasattr(bootstrap, "bootstrap_runtime")
