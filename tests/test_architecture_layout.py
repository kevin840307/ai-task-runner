from pathlib import Path

from runner.workflow.registry import STAGE_REGISTRY
from runner.workflow.stages import (
    AIValidatorStage,
    BaseStage,
    CommandStage,
    PlanStage,
    ReviewStage,
    TaskStage,
)

ROOT = Path(__file__).resolve().parents[1]


def test_stage_implementation_files_are_small_in_number():
    stages = ROOT / "runner" / "workflow" / "stages"
    assert {
        "base_stage.py",
        "core.py",
        "command.py",
        "executor.py",
        "__init__.py",
    } == {path.name for path in stages.glob("*.py")}


def test_workflow_has_one_minimal_type_registry():
    assert STAGE_REGISTRY == {
        "base": BaseStage,
        "task": TaskStage,
        "review": ReviewStage,
        "ai_validator": AIValidatorStage,
        "command": CommandStage,
        "plan": PlanStage,
    }


def test_workflow_runtime_has_only_current_canonical_modules():
    workflow = ROOT / "runner" / "workflow"
    for name in ("flow_engine.py", "results.py", "loader.py", "schema.py", "registry.py"):
        assert (workflow / name).is_file()

    for removed in (
        "lifecycle.py",
        "reducers.py",
        "linear_routing.py",
        "semantic_routing.py",
        "pipeline.py",
        "routing.py",
        "recovery.py",
        "rules.py",
    ):
        assert not (workflow / removed).exists()


def test_ui_workflow_studio_domain_is_not_implemented_in_server():
    server = (ROOT / "ui" / "server.py").read_text(encoding="utf-8")
    studio = (ROOT / "ui" / "workflow_studio_state.py").read_text(encoding="utf-8")
    assert "class WorkflowStudioMixin:" in studio
    assert "class UIState(ProjectRuntimeMixin, WorkflowStudioMixin, WorkflowBuilderMixin):" in server
    for method in (
        "studio_files",
        "studio_save",
        "studio_visual_save",
        "studio_stage_save",
        "studio_validate",
    ):
        assert f"    def {method}(" not in server


def test_dead_execution_mode_endpoint_is_removed():
    server = (ROOT / "ui" / "server.py").read_text(encoding="utf-8")
    runtime = (ROOT / "ui" / "project_runtime_state.py").read_text(encoding="utf-8")
    assert "/api/execution-modes" not in server
    assert "def execution_mode_catalog(" not in runtime
