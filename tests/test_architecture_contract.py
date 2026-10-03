from __future__ import annotations

from pathlib import Path

from runner.workflow.registry import STAGE_REGISTRY


ROOT = Path(__file__).resolve().parents[1]
STAGES = ROOT / "runner" / "workflow" / "stages"
EXECUTION = ROOT / "runner" / "workflow" / "execution"


def test_builtin_stage_modules_stay_one_concrete_stage_per_file():
    expected = {
        "base": "base_stage.py",
        "plan": "plan_stage.py",
        "ai_validator": "ai_validator_stage.py",
        "command": "command_stage.py",
        "handoff": "handoff_stage.py",
    }
    assert set(STAGE_REGISTRY) >= set(expected)

    for stage_type, filename in expected.items():
        stage_class = STAGE_REGISTRY[stage_type]
        module_file = Path(__import__(stage_class.__module__, fromlist=["x"]).__file__).name
        assert module_file == filename

    assert not (STAGES / "core.py").exists()


def test_stage_executor_is_workflow_execution_policy_not_stage_type():
    assert (EXECUTION / "stage_executor.py").is_file()
    assert not (STAGES / "executor.py").exists()
    assert not (STAGES / "stage_executor.py").exists()

    source = (EXECUTION / "stage_executor.py").read_text(encoding="utf-8")
    assert "class StageExecutor" in source
    assert "technical recovery" in source or "technical" in source
    assert "is_transient_error" in source
    assert "changed_project_files" in source


def test_registry_remains_plugin_extensible_without_plugin_specific_branches():
    source = (ROOT / "runner" / "workflow" / "registry.py").read_text(encoding="utf-8")

    assert "def register_stage" in source
    assert "discover_plugins()" in source
    assert "stage_class.spec_class" in source
    assert "STAGE_REGISTRY[stage_type]" in source
    assert "plugin_name ==" not in source
