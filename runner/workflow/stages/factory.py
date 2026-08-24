"""Create Stage instances from plain dictionary definitions."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .ai_stage import AIStage, AIStageSpec
from .plan_stage import PlanStage, PlanStageSpec
from .python_validator import PythonValidatorStage, PythonValidatorStageSpec

STAGE_REGISTRY: dict[str, dict[str, Any]] = {
    "ai": {
        "class": AIStage,
        "spec": AIStageSpec,
        "defaults": {"mode": "readonly", "actor": "model", "runs": 1},
    },
    "plan": {
        "class": PlanStage,
        "spec": PlanStageSpec,
        "defaults": {"mode": "readonly", "actor": "model"},
    },
    "python_validator": {
        "class": PythonValidatorStage,
        "spec": PythonValidatorStageSpec,
        "defaults": {"mode": "write", "actor": "validator"},
    },
}


def create_stage(definition: dict[str, Any]):
    values = deepcopy(definition)
    stage_type = str(values.pop("stage", "ai"))
    try:
        registered = STAGE_REGISTRY[stage_type]
    except KeyError as error:
        raise ValueError(f"unknown stage type: {stage_type}") from error

    options = {**registered["defaults"], **values}
    from ..result_parsers import PARSERS
    from ..rules import CONDITIONS, RESULT_HANDLERS, STATUS_RESOLVERS

    resolvers = {
        "result_handler": RESULT_HANDLERS,
        "parser": PARSERS,
        "result_status": STATUS_RESOLVERS,
        "condition": CONDITIONS,
    }
    for field, mapping in resolvers.items():
        value = options.get(field)
        if isinstance(value, str):
            try:
                options[field] = mapping[value]
            except KeyError as error:
                raise ValueError(f"unknown {field}: {value}") from error

    return registered["class"](registered["spec"](**options))


__all__ = ["STAGE_REGISTRY", "create_stage"]
