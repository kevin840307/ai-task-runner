from runner.workflow.loader import load_workflow
from runner.workflow.registry import create_stage
from runner.workflow.stages import BaseStage, BaseStageSpec, CommandStage, CommandStageSpec, PlanStage, PlanStageSpec


def test_only_behavior_specific_stage_implementations_exist():
    assert BaseStage and PlanStage and CommandStage


def test_retry_is_not_part_of_any_stage_spec():
    assert not hasattr(BaseStageSpec(name="x", status="x"), "retry")
    assert not hasattr(PlanStageSpec(name="plan", status="plan"), "retry")
    assert not hasattr(CommandStageSpec(name="validate", status="validate", command=["check"]), "retry")


def test_final_ai_validation_uses_review_backend_semantics():
    validate = next(item for item in load_workflow() if item.get("name") == "validate_ai")
    assert validate["type"] == "ai_validator"
    stage = create_stage(validate)
    assert stage.backend_mode == "review"


def test_final_ai_validation_yolo_switches_backend_mode():
    from types import SimpleNamespace
    from runner.workflow.stages import AIValidatorStage, AIValidatorStageSpec

    ctx_off = SimpleNamespace(config=SimpleNamespace(ai_validator_yolo=False))
    ctx_on = SimpleNamespace(config=SimpleNamespace(ai_validator_yolo=True))

    default_stage = AIValidatorStage(AIValidatorStageSpec(name="validate_ai"))
    assert default_stage._backend_mode(ctx_off) == "review"
    assert default_stage._backend_mode(ctx_on) == "validation"

    stage_override = AIValidatorStage(
        AIValidatorStageSpec(name="validate_ai", ai_validator_yolo=False)
    )
    assert stage_override._backend_mode(ctx_on) == "review"


def test_plan_stage_is_base_stage_with_only_plan_parser_difference():
    assert issubclass(PlanStage, BaseStage)


def test_file_validation_is_command_semantics():
    validate = next(item for item in load_workflow() if item.get("name") == "validate_file")
    assert validate["type"] == "command"
    assert validate["result_kind"] == "validation"
    assert "validator" not in validate
    assert "clean_work" not in validate
    assert validate["command"].startswith("{python} {validator}")


def test_review_and_validation_result_flags_map_true_to_pass_false_to_fail():
    from runner.workflow.stages import (
        AIValidatorStage,
        AIValidatorStageSpec,
        BaseStage,
        BaseStageSpec,
    )

    review = BaseStage(BaseStageSpec(name="review", profile="review"))
    validator = AIValidatorStage(AIValidatorStageSpec(name="validate_ai"))
    assert review.result_status({"completed": True}) == "pass"
    assert review.result_status({"completed": False}) == "fail"
    assert validator.result_status({"passed": True}) == "pass"
    assert validator.result_status({"passed": False}) == "fail"


def test_create_stage_applies_execute_profile_defaults_before_runtime_construction():
    stage = create_stage({"name": "execute", "type": "base", "profile": "execute"})
    assert stage.spec.mode == "write"
    assert stage.spec.actor == "executor"
    assert stage.spec.allow_project_read is True
    assert stage.spec.track_changes is True
    assert stage.result_kind == "task"


def test_create_stage_applies_review_profile_defaults_before_runtime_construction():
    stage = create_stage({"name": "review", "type": "base", "profile": "review"})
    assert stage.spec.mode == "readonly"
    assert stage.spec.allow_project_read is True
    assert stage.spec.readonly_safety == "observe"
    assert stage.spec.parser is not None
    assert stage.result_kind == "review"
    assert stage.backend_mode == "review"
