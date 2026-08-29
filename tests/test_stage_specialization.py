from runner.workflow.loader import load_workflow
from runner.workflow.stages import (
    BaseStage,
    BaseStageSpec,
    PlanStage,
    PlanStageSpec,
    PythonValidatorStage,
    PythonValidatorStageSpec,
)
from runner.workflow.stages.python_validator import clear_validator_reports


def test_only_base_plan_and_python_validator_stage_implementations_exist():
    assert BaseStage and PlanStage and PythonValidatorStage


def test_retry_is_common_executor_metadata():
    assert BaseStageSpec(name="x", status="x").retry is None
    assert PlanStageSpec(name="plan", status="plan").retry is None
    assert PythonValidatorStageSpec(name="validate", status="validate").retry is None


def test_final_ai_validation_retries_until_pass():
    validate = next(item for item in load_workflow() if item.get("name") == "validate_ai")
    assert validate["type"] == "base"
    assert validate["retry"] == -1
    assert validate["backend_mode"] == "review"


def test_plan_stage_is_base_stage_with_only_plan_parser_difference():
    assert issubclass(PlanStage, BaseStage)


def test_validator_reports_are_cleared_from_configured_work_dir(tmp_path):
    work = tmp_path / "custom-work"
    reports = work / "validator-reports"
    reports.mkdir(parents=True)
    (reports / "old.txt").write_text("old", encoding="utf-8")
    untouched = tmp_path / ".ai-task-runner" / "validator-reports"
    untouched.mkdir(parents=True)

    clear_validator_reports(work)

    assert not reports.exists()
    assert untouched.exists()
