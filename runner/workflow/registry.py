"""Stage registry and construction."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import MISSING, fields
from typing import Any, get_args, get_origin

from ..agent import backend_names
from ..errors import RunnerError
from .profiles import (
    AI_STAGE_PROFILES,
    apply_ai_profile_defaults,
    profile_names,
    stage_profile_semantics,
)
from .stages.ai_validator_stage import AIValidatorStage
from .stages.handoff_stage import HandoffStage
from .stages.plan_stage import PlanStage
from .stages.base_stage import BaseStage
from .stages.command_stage import CommandStage

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
CATALOG_HIDDEN_FIELDS = frozenset()

# Shared presentation hints for built-in/common Stage fields. External Stage
# specs may override with dataclass field metadata {"ui_section": "..."}.
OPTION_SECTION_BY_FIELD = {
    "prompt": "content", "instructions": "content", "detail": "content",
    "command": "content", "cwd": "content",
    "backend": "execution", "model": "execution", "run_state": "execution",
    "mode": "execution", "actor": "execution", "session_policy": "execution",
    "allow_project_read": "execution", "timeout": "execution",
    "readonly_safety": "execution", "track_changes": "execution",
    "tolerate_restored_changes": "execution", "clean_work": "execution",
    "parser": "result", "produces": "result", "result_kind": "result",
    "runs": "result", "required_passes": "result", "min_tasks": "result",
    "structured_retries": "result",
}
DEFAULT_TEST_EXAMPLES = {
    "pass": "Run this isolated Stage successfully and return its normal PASS contract.",
    "fail": "Return the Stage's normal FAIL contract with one concrete unmet condition.",
    "error": "Technical ERROR is injected by the Stage Test harness before the real Stage runs.",
}


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
            "title": str(getattr(stage_class, "ui_title", "") or name),
            "description": str(getattr(stage_class, "ui_description", "") or ""),
            "category": str(getattr(stage_class, "ui_category", "") or "extensions"),
            "result_kind": str(getattr(stage_class, "result_kind", "generic") or "generic"),
            "dynamic_output": str(getattr(stage_class, "result_kind", "generic") or "generic") in {"tasks", "stages"},
            "profiles": deepcopy(AI_STAGE_PROFILES) if name == "base" else {},
            "test_examples": deepcopy(
                getattr(stage_class, "ui_test_examples", None) or DEFAULT_TEST_EXAMPLES
            ),
            "options": [
                _field_info(item, order=index)
                for index, item in enumerate(fields(stage_class.spec_class))
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
    semantics = stage_profile_semantics(definition)
    if semantics == "execute":
        return "task"
    if semantics == "review":
        return "review"
    declared = str(definition.get("result_kind", "") or "")
    if declared:
        return declared
    stage_class = STAGE_REGISTRY.get(str(definition.get("type", "base")))
    return str(getattr(stage_class, "result_kind", "generic") or "generic")


def create_stage(definition: dict[str, Any]):
    values = deepcopy(definition)
    apply_ai_profile_defaults(values)
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


def _field_info(item: Any, *, order: int = 0) -> dict[str, Any]:
    required = item.default is MISSING and item.default_factory is MISSING
    result: dict[str, Any] = {
        "name": item.name,
        "required": required,
        "type": _type_name(item.type),
        "order": int(order),
    }
    raw_type = str(result["type"]).lower().replace("nonetype", "none")
    if item.name == "profile":
        result["type"] = "enum"
        result["values"] = profile_names()
    elif item.name == "mode":
        result["type"] = "enum"
        result["values"] = ["readonly", "write"]
    elif item.name == "backend":
        result["type"] = "enum"
        result["values"] = list(backend_names())
    elif "bool" in raw_type and "none" in raw_type:
        result["type"] = "optional_boolean"
    if item.name == "parser":
        from .results import PARSERS
        result["type"] = "enum"
        result["values"] = sorted(PARSERS)
    if item.name == "produces":
        result["type"] = "enum"
        result["values"] = ["", "tasks", "stages"]
    metadata = getattr(item, "metadata", None) or {}
    description = str(metadata.get("description", "") or "").strip()
    if description:
        result["description"] = description
    section = str(metadata.get("ui_section", "") or OPTION_SECTION_BY_FIELD.get(item.name, "advanced"))
    if section not in {"content", "execution", "result", "advanced"}:
        section = "advanced"
    result["section"] = section
    result["visible"] = bool(metadata.get("ui_visible", True))
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
