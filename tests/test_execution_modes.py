from __future__ import annotations

from pathlib import Path

import pytest

from runner.bootstrap import execute
from runner.config.runtime import RuntimeConfig
from runner.execution_modes import (
    execution_mode_catalog,
    execution_mode_names,
    register_execution_mode,
)


def test_linear_execution_mode_is_builtin_and_requires_workflow():
    assert "linear" in execution_mode_names()
    linear = execution_mode_catalog()["linear"]
    assert linear["requires_workflow"] is True
    assert "Linear Workflow" in str(linear["description"])


def test_registered_non_workflow_mode_can_run_through_shared_bootstrap(tmp_path: Path):
    name = "test_dynamic_handoff_mode"

    def runner(config: RuntimeConfig) -> int:
        assert config.execution_mode == name
        assert config.workflow == []
        return 17

    if name not in execution_mode_names():
        register_execution_mode(
            name,
            runner,
            requires_workflow=False,
            description="test-only dynamic mode",
        )

    config = RuntimeConfig(
        goal="test goal",
        project_root=str(tmp_path),
        execution_mode=name,
        workflow=[],
        human_output=False,
    )
    config.validate()
    assert execute(config) == 17


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


def test_bootstrap_does_not_own_linear_task_runner():
    source = Path(__file__).resolve().parents[1].joinpath("runner", "bootstrap.py").read_text(
        encoding="utf-8"
    )
    assert "TaskRunner" not in source
    assert "execute_execution_mode" in source
