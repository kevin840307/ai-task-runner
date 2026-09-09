from dataclasses import dataclass

from runner.workflow.registry import STAGE_REGISTRY, create_stage, register_stage
from runner.workflow.stages import AIValidatorStage, BaseStage, CommandStage, PlanStage, ReviewStage, TaskStage


def test_registry_contains_only_behavior_types():
    assert STAGE_REGISTRY == {
        "base": BaseStage,
        "task": TaskStage,
        "review": ReviewStage,
        "ai_validator": AIValidatorStage,
        "command": CommandStage,
        "plan": PlanStage,
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
        stage = create_stage({"name": "check", "type": "custom", "status": "Check", "value": 7})
    finally:
        STAGE_REGISTRY.pop("custom", None)
    assert isinstance(stage, CustomStage)
    assert stage.spec.value == 7


def test_routing_metadata_is_not_copied_to_stage():
    stage = create_stage({"name": "write", "status": "Write", "recover": [{"name": "repair"}], "restart_at": "write", "label": "Concrete work"})
    assert not hasattr(stage, "recover")
    assert not hasattr(stage, "workflow")
    assert not hasattr(stage, "restart_at")
    assert not hasattr(stage, "label")


def test_yaml_references_expose_only_structured_parsers():
    from runner.workflow.result_parsers import PARSERS
    import runner.workflow.rules as rules
    assert set(PARSERS) == {"review", "validation"}
    assert not hasattr(rules, "RESULT_HANDLERS")
    assert not hasattr(rules, "STATUS_RESOLVERS")
    assert not hasattr(rules, "CONDITIONS")
