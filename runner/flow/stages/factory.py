"""Create Stage instances from plain dict definitions."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .global_stage import GlobalStage, GlobalStageSpec
from .plan import PlanStage, PlanStageSpec
from .python_validation import PythonValidationStage, PythonValidationStageSpec

STAGE_REGISTRY: dict[str, dict[str, Any]] = {
    "global": {
        "class": GlobalStage,
        "spec": GlobalStageSpec,
        "defaults": {"mode": "readonly", "actor": "model", "reviews": 1},
    },
    "plan": {
        "class": PlanStage,
        "spec": PlanStageSpec,
        "defaults": {"mode": "readonly", "actor": "model"},
    },
    "python_validation": {
        "class": PythonValidationStage,
        "spec": PythonValidationStageSpec,
        "defaults": {"mode": "write", "actor": "validator"},
    },
}


def create_stage(definition: dict[str, Any]):
    values = deepcopy(definition)
    stage_type = str(values.pop("stage", "global"))
    try:
        registered = STAGE_REGISTRY[stage_type]
    except KeyError as error:
        raise ValueError(f"unknown stage type: {stage_type}") from error

    options = {**registered["defaults"], **values}
    from ..behavior import CONDITIONS, RESULT_HANDLERS, STATUS_RESOLVERS
    from ..parsers import PARSERS
    from ..prompts import PROMPT_BUILDERS
    resolvers = {
        "prompt_builder": PROMPT_BUILDERS,
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
