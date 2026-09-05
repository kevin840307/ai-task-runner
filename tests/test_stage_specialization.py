from runner.workflow.loader import load_workflow
from runner.workflow.registry import create_stage
from runner.workflow.stages import BaseStage, BaseStageSpec, CommandStage, CommandStageSpec, PlanStage, PlanStageSpec


def test_only_behavior_specific_stage_implementations_exist():
    assert BaseStage and PlanStage and CommandStage


def test_retry_is_common_executor_metadata():
    assert BaseStageSpec(name="x", status="x").retry is None
    assert PlanStageSpec(name="plan", status="plan").retry is None
    assert CommandStageSpec(name="validate", status="validate", command=["check"]).retry is None


def test_final_ai_validation_retries_until_pass():
    validate = next(item for item in load_workflow() if item.get("name") == "validate_ai")
    assert validate["type"] == "ai_validator"
    stage = create_stage(validate)
    assert stage.retry == -1
    assert stage.backend_mode == "review"


def test_plan_stage_is_base_stage_with_only_plan_parser_difference():
    assert issubclass(PlanStage, BaseStage)


def test_file_validation_is_command_semantics():
    validate = next(item for item in load_workflow() if item.get("name") == "validate_file")
    assert validate["type"] == "command"
    assert validate["result_kind"] == "validation"
    assert "validator" not in validate
    assert "clean_work" not in validate
    assert validate["command"].startswith("{python} {validator}")
