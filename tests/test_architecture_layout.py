from pathlib import Path

from runner.workflow.registry import STAGE_REGISTRY
from runner.workflow.stages import AIValidatorStage, BaseStage, CommandStage, PlanStage, ReviewStage, TaskStage

ROOT = Path(__file__).resolve().parents[1]


def test_stage_ownership_is_inside_workflow():
    assert not (ROOT / "runner/stages").exists()
    stages = ROOT / "runner/workflow/stages"
    assert stages.is_dir()
    for name in ("contracts.py", "executor.py", "base_stage.py", "ai_stage.py", "plan_stage.py", "command.py", "process_stage.py"):
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
