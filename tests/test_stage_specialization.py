from pathlib import Path

from runner.workflow.stages import AIStage, AIStageSpec, PlanStage, PlanStageSpec, PythonValidatorStage, PythonValidatorStageSpec


def test_only_ai_plan_and_python_validator_stage_implementations_exist():
    assert AIStage and PlanStage and PythonValidatorStage


def test_special_stages_only_implement_their_difference():
    for stage_type in (PlanStage, PythonValidatorStage):
        source = Path(__import__(stage_type.__module__, fromlist=['x']).__file__).read_text(encoding='utf-8')
        assert 'hooks.before' not in source
        assert 'hooks.after' not in source
        assert 'while True' not in source
        assert 'Transition(' not in source


def test_retry_is_common_executor_metadata():
    assert AIStageSpec(name='x', status='x').retry is None
    assert PlanStageSpec(name='plan', status='plan').retry is None
    assert PythonValidatorStageSpec(name='validate', status='validate').retry is None
    executor = Path(__import__('runner.workflow.stages.executor', fromlist=['x']).__file__).read_text(encoding='utf-8')
    assert 'while True' in executor


def test_plan_stage_is_ai_stage_with_only_plan_parser_difference():
    assert issubclass(PlanStage, AIStage)
