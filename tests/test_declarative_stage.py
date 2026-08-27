from dataclasses import dataclass

from runner.workflow.registry import STAGE_REGISTRY, create_stage, register_stage
from runner.workflow.stages import BaseStage, PlanStage, PythonValidatorStage
from runner.workflow.stages.python_script import PythonScriptStage


def test_registry_contains_only_behavior_types():
    assert STAGE_REGISTRY == {
        "base": BaseStage,
        "plan": PlanStage,
        "python": PythonValidatorStage,
        "python_script": PythonScriptStage,
    }


@dataclass(frozen=True)
class Spec:
    name: str
    status: str
    value: int = 1


class CustomStage:
    spec_class = Spec

    def __init__(self, spec):
        self.spec = spec
        self.name = spec.name


def test_custom_stage_registration_is_type_to_class_only():
    register_stage("custom", CustomStage)
    try:
        stage = create_stage(
            {"name": "check", "type": "custom", "status": "Check", "value": 7}
        )
    finally:
        STAGE_REGISTRY.pop("custom", None)
    assert isinstance(stage, CustomStage)
    assert stage.spec.value == 7


def test_routing_metadata_is_not_copied_to_stage():
    stage = create_stage(
        {
            "name": "write",
            "status": "Write",
            "recover": [{"name": "repair"}],
            "restart_at": "write",
        }
    )
    assert not hasattr(stage, "recover")
    assert not hasattr(stage, "workflow")
    assert not hasattr(stage, "restart_at")


def test_yaml_references_expose_only_semantic_names():
    from runner.workflow.result_parsers import PARSERS
    from runner.workflow.rules import CONDITIONS, RESULT_HANDLERS, STATUS_RESOLVERS

    assert set(PARSERS) == {"review", "validation"}
    assert set(RESULT_HANDLERS) == {"plan", "task", "review", "validation"}
    assert set(STATUS_RESOLVERS) == {"completed", "validation"}
    assert set(CONDITIONS) == {"ai_validation"}
