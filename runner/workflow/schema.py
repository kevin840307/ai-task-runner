"""Validation helpers for normalized Workflow definitions."""

from __future__ import annotations

from dataclasses import MISSING, fields
from typing import Any

from ..errors import RunnerError
from .registry import STAGE_REGISTRY, stage_result_kind

ROUTING_FIELDS = frozenset({"recover", "restart_at", "repeat", "fresh_after_same_failures", "label", "scope"})
META_FIELDS = frozenset({"name", "type", "validator", *ROUTING_FIELDS})
VALIDATORS = frozenset({"ai"})


def validate_stage(name: str, values: dict[str, Any]) -> None:
    stage_type = values.get("type")
    if not isinstance(stage_type, str) or stage_type not in STAGE_REGISTRY:
        raise RunnerError(f"workflow stage {name} has unknown type: {stage_type}")
    _validate_validator(name, values, stage_type)
    spec_fields = fields(STAGE_REGISTRY[stage_type].spec_class)
    allowed = {field.name for field in spec_fields} | META_FIELDS
    unknown = sorted(str(key) for key in values if key not in allowed)
    if unknown:
        raise RunnerError(f"workflow stage {name} unknown options: {', '.join(unknown)}")
    missing = [
        field.name
        for field in spec_fields
        if field.name != "name"
        and field.default is MISSING
        and field.default_factory is MISSING
        and field.name not in values
    ]
    if missing:
        raise RunnerError(
            f"workflow stage {name} missing required options: {', '.join(missing)}"
        )
    label = values.get("label")
    if label is not None and (not isinstance(label, str) or not label.strip()):
        raise RunnerError(f"workflow stage {name} label must be a non-empty string")
    scope = values.get("scope")
    if scope not in {None, "task"}:
        raise RunnerError(f"workflow stage {name} scope must be task when specified")
    produces = values.get("produces")
    if produces not in {None, "", "tasks"}:
        raise RunnerError(f"workflow stage {name} produces must be tasks when specified")
    _validate_numbers(name, values)


def validate_restart_targets(result: list[dict[str, Any]], top_level: bool) -> None:
    for index, definition in enumerate(result, 1):
        restart_at = definition.get("restart_at")
        if restart_at is None:
            continue
        if not top_level:
            raise RunnerError(f"workflow stage {index} restart_at is only valid at top level")
        if not isinstance(restart_at, str) or not restart_at.strip():
            raise RunnerError(
                f"workflow stage {index} restart_at must be a non-empty stage name"
            )
        preceding = {item.get("name") for item in result[:index] if item.get("name")}
        if restart_at not in preceding:
            raise RunnerError(
                f"workflow stage {index} restart_at must reference its own or an earlier stage name"
            )


def validate_topology(workflow: list[dict[str, Any]]) -> None:
    """Validate only generic flow invariants; Stage capabilities stay optional."""
    files = _file_validation_indexes(workflow)
    finals = _indexes(workflow, "validator", "ai")
    task_nodes = [index for index, item in enumerate(workflow) if item.get("scope") == "task"]

    if len(files) > 1 or len(finals) > 1:
        raise RunnerError("workflow allows at most one file validator and one AI validator")
    if files and finals and files[0] > finals[0]:
        raise RunnerError("file validation must run before AI validation")
    validators = [*files, *finals]
    if validators and max(validators) != len(workflow) - 1:
        raise RunnerError("workflow must end with its final validation stage")

    if task_nodes:
        if task_nodes != list(range(task_nodes[0], task_nodes[-1] + 1)):
            raise RunnerError("task-scoped workflow stages must form one contiguous block")
        if any(workflow[index].get("validator") for index in task_nodes):
            raise RunnerError("validator stages cannot use scope: task")
        if validators and task_nodes[-1] >= min(validators):
            raise RunnerError("task-scoped workflow stages must run before validation")


def workflow_validators(workflow: list[dict[str, Any]]) -> tuple[bool, bool]:
    return bool(_file_validation_indexes(workflow)), bool(
        _indexes(workflow, "validator", "ai")
    )



def workflow_has_task_producer(workflow: list[dict[str, Any]]) -> bool:
    return any(stage_result_kind(definition) == "tasks" for definition in workflow)


def _validate_validator(
    name: str,
    values: dict[str, Any],
    stage_type: str,
) -> None:
    validator = values.get("validator")
    if validator is None:
        return
    if validator != "ai":
        raise RunnerError(f"workflow stage {name} has invalid validator: {validator}")
    if stage_type != "ai_validator":
        raise RunnerError(
            f"workflow stage {name} validator ai requires type: ai_validator"
        )


def _validate_numbers(name: str, values: dict[str, Any]) -> None:
    retry = values.get("retry")
    if retry is not None and (
        not isinstance(retry, int) or isinstance(retry, bool) or retry < -1
    ):
        raise RunnerError(f"workflow stage {name} retry must be -1 or non-negative")
    fresh_after_same_failures = values.get("fresh_after_same_failures")
    if fresh_after_same_failures is not None and (
        not isinstance(fresh_after_same_failures, int)
        or isinstance(fresh_after_same_failures, bool)
        or fresh_after_same_failures <= 0
    ):
        raise RunnerError(
            f"workflow stage {name} fresh_after_same_failures must be a positive integer"
        )
    if fresh_after_same_failures is not None and not values.get("recover"):
        raise RunnerError(
            f"workflow stage {name} fresh_after_same_failures requires recover"
        )
    repeat = values.get("repeat")
    if repeat is not None and (
        not isinstance(repeat, int) or isinstance(repeat, bool) or repeat <= 0
    ):
        raise RunnerError(f"workflow stage {name} repeat must be a positive integer")
    if repeat is not None and repeat > 1 and not values.get("recover"):
        raise RunnerError(f"workflow stage {name} repeat requires recover")
    runs, required = values.get("runs"), values.get("required_passes")
    if runs is not None and (
        not isinstance(runs, int) or isinstance(runs, bool) or runs <= 0
    ):
        raise RunnerError(f"workflow stage {name} runs must be a positive integer")
    if required is not None and (
        not isinstance(required, int) or isinstance(required, bool) or required < 0
    ):
        raise RunnerError(f"workflow stage {name} required_passes must be non-negative")
    if isinstance(runs, int) and isinstance(required, int) and required > runs:
        raise RunnerError(f"workflow stage {name} required_passes cannot exceed runs")


def _file_validation_indexes(workflow: list[dict[str, Any]]) -> list[int]:
    return [
        index
        for index, definition in enumerate(workflow)
        if definition.get("type") == "command"
        and definition.get("result_kind") == "validation"
    ]


def _indexes(workflow: list[dict[str, Any]], field: str, value: str) -> list[int]:
    return [
        index for index, definition in enumerate(workflow) if definition.get(field) == value
    ]


__all__ = [
    "validate_restart_targets",
    "validate_stage",
    "validate_topology",
    "workflow_has_task_producer",
    "workflow_validators",
]
