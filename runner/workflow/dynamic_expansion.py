"""Shared dynamic Workflow expansion for Stage results.

Any Stage may return kind=tasks or kind=stages. The result is expanded into
ordinary Stage definitions inserted immediately after the producing Stage.
The expanded Workflow is durable RunState, so resume never has to re-run the
producer merely to reconstruct child work.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ..errors import ConfigurationError, RunnerError
from ..runtime.run_state import RunState
from .schema import validate_routes, validate_stage
from .stages.base_stage import StageResult

DYNAMIC_META_FIELDS = frozenset({
    "_dynamic_group",
    "_dynamic_path",
    "_dynamic_parent",
    "_dynamic_task_id",
    "_dynamic_task_complete",
    "_dynamic_continue",
    "_dynamic_group_continue",
})


def expand_stage_result(
    *,
    state: RunState,
    workflow: list[dict[str, Any]],
    source_index: int,
    source: dict[str, Any],
    result: StageResult,
    continuation: str,
) -> list[dict[str, Any]] | None:
    """Return a new executable Workflow when a Stage produced child work."""
    if result.status != "pass" or result.kind not in {"tasks", "stages"}:
        return None

    source_name = str(source["name"])
    workflow = _drop_previous_expansion(state, workflow, source_name)
    # source_index is stable because previous children are always after their producer.
    source_index = next(
        index for index, item in enumerate(workflow)
        if str(item["name"]) == source_name
    )

    state.expansion_counter += 1
    group = f"{source_name}__g{state.expansion_counter}"
    parent_path = [
        str(item) for item in source.get("_dynamic_path", [])
        if isinstance(item, str) and item
    ]
    path = [*parent_path, group]

    raw = result.data if result.data is not None else result.output
    children = _expand_stages(raw, source_name, group, path, result_kind=result.kind)

    if not children:
        raise ConfigurationError(
            f"dynamic Stage {source_name} produced no child stages"
        )

    group_continue = _effective_continuation(source, continuation)
    for child in children:
        child["_dynamic_group_continue"] = group_continue
    children[-1]["_dynamic_continue"] = group_continue

    expanded = [
        *workflow[: source_index + 1],
        *children,
        *workflow[source_index + 1 :],
    ]
    validate_routes(expanded)
    state.dynamic_groups[source_name] = group
    state.expanded_workflow = deepcopy(expanded)
    return expanded


def activate_dynamic_task(state: RunState, definition: dict[str, Any]) -> None:
    task_id = str(definition.get("_dynamic_task_id", "") or "")
    if not task_id:
        return
    for index, task in enumerate(state.tasks):
        if task.id == task_id:
            state.current = index
            return
    raise ConfigurationError(
        f"dynamic Stage {definition['name']} references unknown task: {task_id}"
    )


def dynamic_done_target(definition: dict[str, Any]) -> str | None:
    if definition.get("_dynamic_group"):
        return str(definition.get("_dynamic_group_continue", "next") or "next")
    return None


def _effective_continuation(source: dict[str, Any], continuation: str) -> str:
    if continuation == "next" and source.get("_dynamic_continue"):
        return str(source["_dynamic_continue"])
    if continuation == "done" and source.get("_dynamic_group"):
        return str(source.get("_dynamic_group_continue", "next") or "next")
    return continuation


def _drop_previous_expansion(
    state: RunState,
    workflow: list[dict[str, Any]],
    source_name: str,
) -> list[dict[str, Any]]:
    old_group = state.dynamic_groups.pop(source_name, "")
    if not old_group:
        return list(workflow)
    return [
        item for item in workflow
        if old_group not in (item.get("_dynamic_path") or [])
    ]


def _expand_stages(
    value: Any,
    source_name: str,
    group: str,
    path: list[str],
    *,
    result_kind: str,
) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise RunnerError(
                f"Stage {source_name} stages result must be valid JSON: {error}"
            ) from error
    raw = value.get("stages") if isinstance(value, dict) else None
    if not isinstance(raw, list) or not raw:
        raise RunnerError(
            f"Stage {source_name} {result_kind} result must provide a non-empty stages array; "
            "Runner does not infer child Stage structure from tasks"
        )

    clean: list[dict[str, Any]] = []
    local_names: list[str] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise RunnerError(f"stages[{index}] must be an object")
        definition = deepcopy(item)
        name = str(definition.get("name", "") or "").strip()
        if not name:
            raise RunnerError(f"stages[{index}].name must be a non-empty string")
        definition.setdefault("type", "base")
        if any(str(key).startswith("_dynamic_") for key in definition):
            raise RunnerError(
                f"stages[{index}] contains Runner-owned dynamic metadata"
            )
        task_id = str(definition.pop("task_id", "") or "")
        task_complete = bool(definition.pop("task_complete", False))
        validate_stage(name, definition)
        if task_id:
            definition["_producer_task_id"] = task_id
        if task_complete:
            definition["_producer_task_complete"] = True
        clean.append(definition)
        local_names.append(name)

    if len(set(local_names)) != len(local_names):
        raise RunnerError("dynamic stages must have unique names")

    name_map = {
        name: f"{group}__{_safe_name(name)}"
        for name in local_names
    }
    result: list[dict[str, Any]] = []
    for definition in clean:
        local_name = str(definition["name"])
        child = deepcopy(definition)
        child["name"] = name_map[local_name]
        routes = child.get("routes")
        if isinstance(routes, dict):
            child["routes"] = {
                status: name_map.get(str(target), target)
                for status, target in routes.items()
            }
        targets = child.get("targets")
        if isinstance(targets, list):
            child["targets"] = [
                name_map.get(str(target), target)
                for target in targets
            ]
        task_id = str(child.pop("_producer_task_id", "") or "")
        task_complete = bool(child.pop("_producer_task_complete", False))
        child.update({
            "_dynamic_group": group,
            "_dynamic_path": list(path),
            "_dynamic_parent": source_name,
        })
        if task_id:
            child["_dynamic_task_id"] = task_id
        if task_complete:
            child["_dynamic_task_complete"] = True
        result.append(child)
    return result


def _safe_name(value: str) -> str:
    normalized = "".join(
        char if char.isalnum() or char in {"_", "-"} else "_"
        for char in str(value)
    ).strip("_")
    return normalized or "stage"


__all__ = [
    "DYNAMIC_META_FIELDS",
    "activate_dynamic_task",
    "dynamic_done_target",
    "expand_stage_result",
]
