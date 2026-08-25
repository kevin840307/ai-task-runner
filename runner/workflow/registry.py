"""Minimal Stage type registry and generic Stage construction."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..errors import RunnerError
from .stages.base_stage import BaseStage
from .stages.plan_stage import PlanStage
from .stages.python_validator import PythonValidatorStage

STAGE_REGISTRY: dict[str, type[Any]] = {
    "base": BaseStage,
    "plan": PlanStage,
    "python": PythonValidatorStage,
}
ROUTING_FIELDS = frozenset(
    {
        "validator",
        "recover",
        "restart_at",
        "_workflow_index",
        "_task_index",
        "_task_last",
    }
)


def register_stage(name: str, stage_class: type[Any]) -> None:
    """Register one behavior type. Workflow instances and routing stay in YAML."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Stage type must be a non-empty string")
    if name in STAGE_REGISTRY:
        raise ValueError(f"duplicate Stage registration: {name}")
    if not isinstance(getattr(stage_class, "spec_class", None), type):
        raise ValueError(f"Stage {name} must expose spec_class")
    STAGE_REGISTRY[name] = stage_class


def _resolve_references(values: dict[str, Any]) -> None:
    from .result_parsers import PARSERS
    from .rules import CONDITIONS, RESULT_HANDLERS, STATUS_RESOLVERS

    for field, mapping in {
        "result_handler": RESULT_HANDLERS,
        "parser": PARSERS,
        "result_status": STATUS_RESOLVERS,
        "condition": CONDITIONS,
    }.items():
        value = values.get(field)
        if not isinstance(value, str):
            continue
        try:
            values[field] = mapping[value]
        except KeyError as error:
            raise RunnerError(f"unknown {field}: {value}") from error


def create_stage(definition: dict[str, Any]):
    """Build one Stage from an already-normalized YAML instance."""
    values = deepcopy(definition)
    stage_type = str(values.pop("type", "base"))
    name = str(values.get("name", ""))
    for field in ROUTING_FIELDS:
        values.pop(field, None)
    try:
        stage_class = STAGE_REGISTRY[stage_type]
    except KeyError as error:
        raise RunnerError(f"unknown workflow Stage type: {stage_type}") from error

    _resolve_references(values)
    try:
        return stage_class(stage_class.spec_class(**values))
    except TypeError as error:
        raise RunnerError(f"invalid workflow Stage {name or stage_type}: {error}") from error


__all__ = ["STAGE_REGISTRY", "create_stage", "register_stage"]
