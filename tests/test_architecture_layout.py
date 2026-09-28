from pathlib import Path

from runner.workflow.registry import STAGE_REGISTRY
from runner.workflow.stages import AIValidatorStage, BaseStage, CommandStage, PlanStage, ReviewStage, TaskStage

ROOT = Path(__file__).resolve().parents[1]


def test_stage_ownership_is_inside_workflow():
    assert not (ROOT / "runner/stages").exists()
    stages = ROOT / "runner/workflow/stages"
    assert stages.is_dir()
    for name in ("contracts.py", "executor.py", "base_stage.py", "ai_stage.py", "plan_stage.py", "command.py"):
        assert (stages / name).is_file()
    assert not (stages / "factory.py").exists()


def test_workflow_has_one_minimal_type_registry():
    assert STAGE_REGISTRY == {
        "base": BaseStage,
        "task": TaskStage,
        "review": ReviewStage,
        "ai_validator": AIValidatorStage,
        "command": CommandStage,
        "plan": PlanStage,
    }


def test_workflow_runtime_has_clear_canonical_modules():
    workflow = ROOT / "runner" / "workflow"
    for name in (
        "flow_engine.py",
        "linear_routing.py",
        "semantic_routing.py",
        "reducers.py",
    ):
        assert (workflow / name).is_file()

    # Compatibility shims may remain, but canonical runtime behavior belongs in
    # the responsibility-matched modules above.
    assert (ROOT / "runner" / "workflow_runner.py").is_file()
    assert (ROOT / "runner" / "task_runner.py").is_file()
    assert (workflow / "pipeline.py").is_file()
    assert (workflow / "routing.py").is_file()
    assert (workflow / "recovery.py").is_file()
    assert (workflow / "rules.py").is_file()


def test_ui_workflow_studio_domain_is_not_implemented_in_server():
    server = (ROOT / "ui" / "server.py").read_text(encoding="utf-8")
    studio = (ROOT / "ui" / "workflow_studio_state.py").read_text(encoding="utf-8")

    assert "class WorkflowStudioMixin:" in studio
    assert "class UIState(ProjectRuntimeMixin, WorkflowStudioMixin, WorkflowBuilderMixin):" in server
    assert "    def studio_files(" not in server
    assert "    def studio_save(" not in server
    assert "    def studio_visual_save(" not in server
    assert "    def studio_stage_save(" not in server
    assert "    def studio_validate(" not in server
