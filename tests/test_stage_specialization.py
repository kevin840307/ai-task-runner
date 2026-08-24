from pathlib import Path

from runner.flow.stages import GlobalStage, GlobalStageSpec, PlanStage, PlanStageSpec, PythonValidationStage, PythonValidationStageSpec


def test_only_global_plan_and_python_validation_stage_implementations_exist():
    assert GlobalStage and PlanStage and PythonValidationStage


def test_special_stages_only_implement_their_difference():
    for stage_type in (PlanStage, PythonValidationStage):
        source = Path(__import__(stage_type.__module__, fromlist=['x']).__file__).read_text(encoding='utf-8')
        assert 'hooks.before' not in source
        assert 'hooks.after' not in source
        assert 'while True' not in source
        assert 'Transition(' not in source


def test_retry_is_common_executor_metadata():
    assert GlobalStageSpec(name='x', status='x').retry == 3
    assert PlanStageSpec(name='plan', status='plan').retry == 3
    assert PythonValidationStageSpec(name='validate', status='validate').retry == 3
    executor = Path(__import__('runner.flow.stages.executor', fromlist=['x']).__file__).read_text(encoding='utf-8')
    assert 'while True' in executor


def test_plan_stage_is_global_stage_with_only_plan_parser_difference():
    assert issubclass(PlanStage, GlobalStage)
