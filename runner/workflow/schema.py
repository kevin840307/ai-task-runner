"""Validation helpers for normalized Workflow definitions."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from ..errors import RunnerError
from .registry import STAGE_REGISTRY

ROUTING_FIELDS = frozenset({"recover", "restart_at"})
META_FIELDS = frozenset({"name", "type", "validator", *ROUTING_FIELDS})
VALIDATORS = frozenset({"file", "ai"})


def validate_stage(name: str, values: dict[str, Any]) -> None:
    stage_type = values.get("type")
    if not isinstance(stage_type, str) or stage_type not in STAGE_REGISTRY:
        raise RunnerError(f"workflow stage {name} has unknown type: {stage_type}")
    _validate_validator(name, values, stage_type)
    allowed = {
        field.name for field in fields(STAGE_REGISTRY[stage_type].spec_class)
    } | META_FIELDS
    unknown = sorted(str(key) for key in values if key not in allowed)
    if unknown:
        raise RunnerError(f"workflow stage {name} unknown options: {', '.join(unknown)}")
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
    plans = _indexes(workflow, "type", "plan")
    files = _indexes(workflow, "validator", "file")
    finals = _indexes(workflow, "validator", "ai")
    if len(plans) > 1:
        raise RunnerError("workflow allows at most one top-level planning stage")
    if len(files) > 1 or len(finals) > 1 or not (files or finals):
        raise RunnerError("workflow requires one file validator, one AI validator, or both")
    if files and finals and files[0] > finals[0]:
        raise RunnerError("file validation must run before AI validation")
    if (finals[0] if finals else files[0]) != len(workflow) - 1:
        raise RunnerError("workflow must end with its final validation stage")


def workflow_validators(workflow: list[dict[str, Any]]) -> tuple[bool, bool]:
    return bool(_indexes(workflow, "validator", "file")), bool(
        _indexes(workflow, "validator", "ai")
    )


def workflow_has_planning(workflow: list[dict[str, Any]]) -> bool:
    return bool(_indexes(workflow, "type", "plan"))


def _validate_validator(
    name: str,
    values: dict[str, Any],
    stage_type: str,
) -> None:
    validator = values.get("validator")
    if validator is None:
        return
    if validator not in VALIDATORS:
        raise RunnerError(f"workflow stage {name} has invalid validator: {validator}")
    expected = "python" if validator == "file" else "base"
    if stage_type != expected:
        raise RunnerError(
            f"workflow stage {name} validator {validator} requires type: {expected}"
        )


def _validate_numbers(name: str, values: dict[str, Any]) -> None:
    retry = values.get("retry")
    if retry is not None and (
        not isinstance(retry, int) or isinstance(retry, bool) or retry < -1
    ):
        raise RunnerError(f"workflow stage {name} retry must be -1 or non-negative")
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


def _indexes(workflow: list[dict[str, Any]], field: str, value: str) -> list[int]:
    return [
        index for index, definition in enumerate(workflow) if definition.get(field) == value
    ]


__all__ = [
    "validate_restart_targets",
    "validate_stage",
    "validate_topology",
    "workflow_has_planning",
    "workflow_validators",
]
