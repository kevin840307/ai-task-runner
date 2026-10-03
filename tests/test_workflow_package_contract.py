from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "runner" / "workflow"
STAGES = WORKFLOW / "stages"
EXECUTION = WORKFLOW / "execution"


def test_stage_package_has_one_concrete_stage_per_file_and_no_core_bucket():
    assert not (STAGES / "core.py").exists()
    expected = {
        "base_stage.py",
        "plan_stage.py",
        "ai_validator_stage.py",
        "command_stage.py",
        "handoff_stage.py",
        "__init__.py",
    }
    assert {path.name for path in STAGES.glob("*.py")} == expected


def test_stage_executor_is_execution_policy_not_a_stage_module():
    assert (EXECUTION / "stage_executor.py").is_file()
    assert (EXECUTION / "__init__.py").is_file()
    assert not (STAGES / "executor.py").exists()
    assert not (STAGES / "stage_executor.py").exists()

    executor = (EXECUTION / "stage_executor.py").read_text(encoding="utf-8")
    assert "class StageExecutor" in executor
    assert "stage_retries" in executor
    assert "is_transient_error" in executor
    assert "_fresh_session" in executor
    assert "resolve_stage_target" not in executor
    assert "routes" not in executor


def test_flow_engine_and_workflow_runner_depend_on_execution_boundary():
    flow = (WORKFLOW / "flow_engine.py").read_text(encoding="utf-8")
    runner = (ROOT / "runner" / "workflow_runner.py").read_text(encoding="utf-8")

    assert "from .execution import StageExecutor" in flow
    assert "from .workflow.execution import StageExecutor" in runner
    assert "from .stages.executor" not in flow
    assert "from .workflow.stages.executor" not in runner


def test_removed_stage_contracts_do_not_reappear_in_runtime_packages():
    runtime_files = [
        *WORKFLOW.rglob("*.py"),
        *(ROOT / "runner" / "runtime").rglob("*.py"),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)

    assert "task_step" not in text
    assert "scope: task" not in text
    assert "class TaskStage" not in text
    assert "class ReviewStage" not in text
    assert '"task": TaskStage' not in text
    assert '"review": ReviewStage' not in text
