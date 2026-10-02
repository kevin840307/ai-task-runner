"""Stage registry and construction."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import MISSING, fields
from typing import Any, get_args, get_origin

from ..errors import RunnerError
from .stages.core import (
    AIValidatorStage,
    HandoffStage,
    PlanStage,
)
from .stages.base_stage import BaseStage
from .stages.command import CommandStage

STAGE_REGISTRY: dict[str, type[Any]] = {
    "base": BaseStage,
    "handoff": HandoffStage,
    "ai_validator": AIValidatorStage,
    "command": CommandStage,
    "plan": PlanStage,
}
NODE_FIELDS = frozenset({"validator", "routes", "label", "error_policy", "_workflow_index"})
RUNNER_INTERNAL_FIELDS = frozenset({
    "_dynamic_group", "_dynamic_path", "_dynamic_parent", "_dynamic_task_id",
    "_dynamic_task_complete", "_dynamic_continue", "_dynamic_group_continue",
})
CATALOG_HIDDEN_FIELDS = frozenset({"fresh_session_each_run", "fresh_session_on_start"})


def register_stage(name: str, stage_class: type[Any]) -> None:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Stage type must be a non-empty string")
    if name in STAGE_REGISTRY:
        raise ValueError(f"duplicate Stage registration: {name}")
    if not isinstance(getattr(stage_class, "spec_class", None), type):
        raise ValueError(f"Stage {name} must expose spec_class")
    STAGE_REGISTRY[name] = stage_class


def stage_catalog() -> dict[str, dict[str, Any]]:
    from ..plugins.registry import discover_plugins

    discover_plugins()
    return {
        name: {
            "type": name,
            "options": [
                _field_info(item)
                for item in fields(stage_class.spec_class)
                if item.name != "name"
                and item.name not in CATALOG_HIDDEN_FIELDS
                and not (item.name == "profile" and name != "base")
            ],
        }
        for name, stage_class in sorted(STAGE_REGISTRY.items())
    }


def workflow_catalog() -> dict[str, Any]:
    return {
        "stage_types": stage_catalog(),
        "node_options": {
            "label": {"type": "string"},
            "routes": {
                "type": "object",
                "description": "pass/fail -> next, done, stop, or another Stage",
            },
            "error_policy": {
                "type": "object",
                "description": "technical ERROR retry count; -1 means unlimited",
            },
        },
    }


def stage_result_kind(definition: dict[str, Any]) -> str:
    # An explicit producer contract is stronger than an AI behavior profile.
    # This keeps dynamic expansion generic: any Stage/profile may emit tasks/stages.
    produces = str(definition.get("produces", "") or "")
    if produces:
        return produces
    if definition.get("type", "base") == "base":
        profile = str(definition.get("profile", "generic") or "generic")
        if profile == "execute":
            return "task"
        if profile == "review":
            return "review"
    declared = str(definition.get("result_kind", "") or "")
    if declared:
        return declared
    stage_class = STAGE_REGISTRY.get(str(definition.get("type", "base")))
    return str(getattr(stage_class, "result_kind", "generic") or "generic")


def create_stage(definition: dict[str, Any]):
    values = deepcopy(definition)
    stage_type = str(values.pop("type", "base"))
    name = str(values.get("name", ""))
    for field in (*NODE_FIELDS, *RUNNER_INTERNAL_FIELDS):
        values.pop(field, None)

    try:
        stage_class = STAGE_REGISTRY[stage_type]
    except KeyError as error:
        raise RunnerError(f"unknown workflow Stage type: {stage_type}") from error

    parser = values.get("parser")
    if isinstance(parser, str):
        from .results import PARSERS
        try:
            values["parser"] = PARSERS[parser]
        except KeyError as error:
            raise RunnerError(f"unknown parser: {parser}") from error

    try:
        return stage_class(stage_class.spec_class(**values))
    except TypeError as error:
        raise RunnerError(f"invalid workflow Stage {name or stage_type}: {error}") from error


def _field_info(item: Any) -> dict[str, Any]:
    required = item.default is MISSING and item.default_factory is MISSING
    result: dict[str, Any] = {
        "name": item.name,
        "required": required,
        "type": _type_name(item.type),
    }
    if item.name == "profile":
        result["type"] = "enum"
        result["values"] = ["generic", "execute", "review"]
    if item.name == "parser":
        from .results import PARSERS
        result["type"] = "enum"
        result["values"] = sorted(PARSERS)
    if item.name == "produces":
        result["type"] = "enum"
        result["values"] = ["", "tasks", "stages"]
    if item.name == "session_policy":
        result["type"] = "enum"
        result["values"] = ["auto", "main", "role", "fresh"]
    if not required:
        default = item.default if item.default is not MISSING else item.default_factory()
        if default is None or isinstance(default, (str, int, float, bool, list, dict, tuple)):
            result["default"] = default
    return result


def _type_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is None:
        return getattr(annotation, "__name__", str(annotation).replace("typing.", ""))
    args = ", ".join(_type_name(arg) for arg in get_args(annotation))
    name = getattr(origin, "__name__", str(origin).replace("typing.", ""))
    return f"{name}[{args}]" if args else name


__all__ = [
    "STAGE_REGISTRY",
    "create_stage",
    "register_stage",
    "stage_catalog",
    "stage_result_kind",
    "workflow_catalog",
]
