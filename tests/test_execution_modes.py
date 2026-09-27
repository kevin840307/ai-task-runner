from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.bootstrap import execute
from runner.config.runtime import RuntimeConfig
from runner.execution_modes import execution_mode_catalog, execution_mode_names


def test_linear_execution_mode_is_the_only_current_mode_and_requires_workflow():
    assert execution_mode_names() == ("linear",)
    linear = execution_mode_catalog()["linear"]
    assert linear["requires_workflow"] is True
    assert "Linear Workflow" in str(linear["description"])


def test_execution_mode_metadata_does_not_register_alternate_runners():
    import runner.execution_modes as modes

    assert not hasattr(modes, "register_execution_mode")
    assert not hasattr(modes, "execute_execution_mode")


def test_unknown_execution_mode_fails_validation(tmp_path: Path):
    config = RuntimeConfig(
        goal="test goal",
        project_root=str(tmp_path),
        execution_mode="missing-mode",
        workflow=[],
        human_output=False,
    )
    with pytest.raises(ValueError, match="unsupported execution_mode"):
        config.validate()


def test_bootstrap_routes_current_execution_through_workflow_runner():
    source = Path(__file__).resolve().parents[1].joinpath("runner", "bootstrap.py").read_text(
        encoding="utf-8"
    )
    assert "TaskRunner" not in source
    assert "execute_execution_mode" not in source
    assert "WorkflowRunner" in source


def test_durable_run_state_rejects_execution_mode_change_on_resume(tmp_path: Path):
    from runner.errors import ConfigurationError
    from runner.runtime.run_state import StateStore

    work = tmp_path / ".runner"
    store = StateStore(tmp_path, work)
    state = store.load_or_create(
        "goal",
        resume=False,
        force_new=False,
        execution_mode="linear",
    )
    store.save(state)

    with pytest.raises(ConfigurationError, match="execution_mode"):
        store.load_or_create(
            "goal",
            resume=True,
            force_new=False,
            execution_mode="future-mode",
        )


def test_legacy_state_without_execution_mode_resumes_as_linear(tmp_path: Path):
    from runner.runtime.run_state import StateStore

    work = tmp_path / ".runner"
    work.mkdir()
    (work / "state.json").write_text(
        json.dumps({"run_id": "legacy", "goal": "g", "project_root": str(tmp_path)}),
        encoding="utf-8",
    )
    store = StateStore(tmp_path, work)
    state = store.load_or_create(
        "goal",
        resume=True,
        force_new=False,
        execution_mode="linear",
    )
    assert state.execution_mode == "linear"


def test_yaml_batch_rejects_non_linear_execution_mode(tmp_path: Path):
    from runner.errors import ConfigurationError

    script = tmp_path / "tasks.yaml"
    script.write_text("- prompt: x\n  validator: ai\n", encoding="utf-8")
    config = RuntimeConfig(
        project_root=str(tmp_path),
        script=str(script),
        execution_mode="future-mode",
        workflow=[],
        human_output=False,
    )

    with pytest.raises(ConfigurationError, match="YAML script batching.*linear"):
        execute(config)
