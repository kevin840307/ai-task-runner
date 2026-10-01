"""Validation for the minimal Workflow contract."""

from __future__ import annotations

from dataclasses import MISSING, fields
from typing import Any

from ..errors import RunnerError
from .registry import STAGE_REGISTRY, stage_result_kind

NODE_FIELDS = frozenset({"routes", "label", "scope", "error_policy"})
META_FIELDS = frozenset({"name", "type", "validator", "max_failures", *NODE_FIELDS})


def validate_stage(name: str, values: dict[str, Any]) -> None:
    stage_type = values.get("type")
    if not isinstance(stage_type, str) or stage_type not in STAGE_REGISTRY:
        raise RunnerError(f"workflow stage {name} has unknown type: {stage_type}")

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

    if values.get("validator") not in {None, "ai"}:
        raise RunnerError(f"workflow stage {name} validator must be ai")
    if values.get("validator") == "ai" and stage_type != "ai_validator":
        raise RunnerError(f"workflow stage {name} validator ai requires type: ai_validator")

    label = values.get("label")
    if label is not None and (not isinstance(label, str) or not label.strip()):
        raise RunnerError(f"workflow stage {name} label must be a non-empty string")

    scope = values.get("scope")
    if scope not in {None, "task"}:
        raise RunnerError(f"workflow stage {name} scope must be task when specified")

    for legacy_session_option in ("fresh_session_each_run", "fresh_session_on_start"):
        if legacy_session_option in values:
            raise RunnerError(
                f"workflow stage {name} {legacy_session_option} was removed; "
                "use session_policy: fresh instead"
            )

    session_policy = values.get("session_policy", "auto")
    if session_policy not in {"auto", "main", "role", "fresh"}:
        raise RunnerError(
            f"workflow stage {name} session_policy must be auto, main, role, or fresh"
        )
    if session_policy != "auto" and values.get("session_key"):
        raise RunnerError(
            f"workflow stage {name} session_key is only valid with session_policy: auto"
        )

    targets = values.get("targets")
    if stage_type == "handoff":
        if not isinstance(targets, list) or not targets:
            raise RunnerError(f"workflow stage {name} handoff targets must be a non-empty array")
        if any(not isinstance(target, str) or not target.strip() for target in targets):
            raise RunnerError(f"workflow stage {name} handoff targets must be non-empty strings")
        if len(set(targets)) != len(targets):
            raise RunnerError(f"workflow stage {name} handoff targets must be unique")

    produces = values.get("produces")
    if produces not in {None, "", "tasks"}:
        raise RunnerError(f"workflow stage {name} produces must be tasks when specified")

    max_failures = values.get("max_failures")
    if max_failures is not None:
        if stage_type != "review":
            raise RunnerError(
                f"workflow stage {name} max_failures is only valid for type: review"
            )
        if (
            not isinstance(max_failures, int)
            or isinstance(max_failures, bool)
            or max_failures <= 0
        ):
            raise RunnerError(
                f"workflow stage {name} max_failures must be a positive integer"
            )

    runs = values.get("runs")
    required = values.get("required_passes")
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

    _validate_routes(name, values.get("routes"))
    policy = values.get("error_policy")
    if policy is not None:
        if not isinstance(policy, dict) or set(policy) != {"retries"}:
            raise RunnerError(f"workflow stage {name} error_policy requires only retries")
        retries = policy["retries"]
        if not isinstance(retries, int) or isinstance(retries, bool) or retries < -1:
            raise RunnerError(f"workflow stage {name} error_policy.retries must be -1 or non-negative")


def _validate_routes(name: str, routes: Any) -> None:
    if routes is None:
        return
    if not isinstance(routes, dict) or not routes:
        raise RunnerError(f"workflow stage {name} routes must be a non-empty object")
    unknown = sorted(str(key) for key in routes if key not in {"pass", "fail"})
    if unknown:
        raise RunnerError(
            f"workflow stage {name} routes supports only pass/fail; "
            f"unknown: {', '.join(unknown)}"
        )
    for status, target in routes.items():
        if not isinstance(target, str) or not target.strip():
            raise RunnerError(
                f"workflow stage {name} routes.{status} must be a non-empty target"
            )


def validate_routes(workflow: list[dict[str, Any]]) -> None:
    names = {str(item["name"]) for item in workflow}
    for definition in workflow:
        for status, target in (definition.get("routes") or {}).items():
            if target not in {"next", "done", "stop"} and target not in names:
                raise RunnerError(
                    f"workflow stage {definition['name']} routes.{status} "
                    f"references unknown stage: {target}"
                )
        for target in definition.get("targets") or []:
            if target not in names:
                raise RunnerError(
                    f"workflow stage {definition['name']} handoff target "
                    f"references unknown stage: {target}"
                )
            if target == definition["name"]:
                raise RunnerError(
                    f"workflow stage {definition['name']} cannot hand off to itself"
                )


def validate_topology(workflow: list[dict[str, Any]]) -> None:
    task_nodes = [
        index for index, item in enumerate(workflow) if item.get("scope") == "task"
    ]
    if not task_nodes:
        return
    if task_nodes != list(range(task_nodes[0], task_nodes[-1] + 1)):
        raise RunnerError("task-scoped workflow stages must form one contiguous block")
    if any(stage_result_kind(workflow[index]) == "validation" for index in task_nodes):
        raise RunnerError("validator stages cannot use scope: task")


def workflow_validators(workflow: list[dict[str, Any]]) -> tuple[bool, bool]:
    file_validation = any(
        item.get("type") == "command" and item.get("result_kind") == "validation"
        for item in workflow
    )
    ai_validation = any(
        item.get("type") == "ai_validator" and item.get("validator") == "ai"
        for item in workflow
    )
    return file_validation, ai_validation


def workflow_has_task_producer(workflow: list[dict[str, Any]]) -> bool:
    return any(stage_result_kind(item) == "tasks" for item in workflow)


__all__ = [
    "validate_routes",
    "validate_stage",
    "validate_topology",
    "workflow_has_task_producer",
    "workflow_validators",
]
