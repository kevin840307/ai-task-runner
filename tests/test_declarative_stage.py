from dataclasses import dataclass

from runner.workflow.registry import STAGE_REGISTRY, create_stage, register_stage
from runner.workflow.stages import (
    AIValidatorStage,
    BaseStage,
    CommandStage,
    DiscussionStage,
    HandoffStage,
    PlanStage,
    ReviewStage,
    TaskStage,
)


def test_registry_contains_only_behavior_types():
    assert STAGE_REGISTRY == {
        "base": BaseStage,
        "discussion": DiscussionStage,
        "handoff": HandoffStage,
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


def test_graph_metadata_is_not_copied_to_stage_behavior():
    stage = create_stage({
        "name": "write",
        "status": "Write",
        "label": "Concrete work",
        "scope": "task",
        "routes": {"fail": "stop"},
    })
    assert not hasattr(stage, "label")
    assert not hasattr(stage, "scope")
    assert not hasattr(stage, "routes")


def test_yaml_references_expose_only_structured_parsers():
    from runner.workflow.results import PARSERS
    assert set(PARSERS) == {"review", "validation"}
