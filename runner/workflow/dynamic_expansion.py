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
from ..runtime import events as progress
from ..runtime.run_state import RunState, Task
from .schema import validate_routes, validate_stage
from .profiles import apply_ai_profile_defaults
from .contracts import StageResult

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
    task_id_map: dict[str, str] = {}
    if result.kind == "tasks":
        task_id_map = _install_task_group(state, source_name, group, raw)
    children = _expand_stages(
        raw,
        source_name,
        group,
        path,
        result_kind=result.kind,
        task_id_map=task_id_map,
        reserved_names={str(item["name"]) for item in workflow},
    )

    if not children:
        raise ConfigurationError(
            f"dynamic Stage {source_name} produced no child stages"
        )
    if result.kind == "tasks":
        _validate_task_bindings(source_name, task_id_map.values(), children)

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
        _remove_task_groups(state, {source_name})
        return list(workflow)

    removed_names = {
        str(item.get("name", ""))
        for item in workflow
        if old_group in (item.get("_dynamic_path") or [])
    }
    affected = {source_name, *[name for name in removed_names if name]}
    _remove_task_groups(state, affected)
    for name in removed_names:
        state.dynamic_groups.pop(name, None)

    return [
        item for item in workflow
        if old_group not in (item.get("_dynamic_path") or [])
    ]


def _install_task_group(
    state: RunState,
    source_name: str,
    group: str,
    value: Any,
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RunnerError(
            f"Stage {source_name} tasks result must be an object containing tasks and stages"
        )
    raw_tasks = value.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks or any(
        not isinstance(task, Task) for task in raw_tasks
    ):
        raise RunnerError(
            f"Stage {source_name} tasks result must contain validated Task objects"
        )

    _remove_task_groups(state, {source_name})
    mapping: dict[str, str] = {}
    installed: list[Task] = []
    used_ids = {task.id for task in state.tasks}
    for index, original in enumerate(raw_tasks, 1):
        task = deepcopy(original)
        base = _safe_name(task.id or f"task_{index}")
        candidate = f"{group}__{base}"
        suffix = 2
        while candidate in used_ids:
            candidate = f"{group}__{base}_{suffix}"
            suffix += 1
        mapping[original.id] = candidate
        task.id = candidate
        task.status = "pending"
        installed.append(task)
        used_ids.add(candidate)

    state.tasks.extend(installed)
    state.dynamic_task_groups[source_name] = [task.id for task in installed]
    progress.show_todo(state)
    if state.current > len(state.tasks):
        state.current = len(state.tasks)
    return mapping


def _remove_task_groups(state: RunState, sources: set[str]) -> None:
    remove_ids: set[str] = set()
    for source in sources:
        remove_ids.update(state.dynamic_task_groups.pop(source, []))
    if not remove_ids:
        return
    state.tasks = [task for task in state.tasks if task.id not in remove_ids]
    for key in [
        key for key in state.review_failures
        if any(key.endswith(f"::{task_id}") for task_id in remove_ids)
    ]:
        state.review_failures.pop(key, None)
    if state.current > len(state.tasks):
        state.current = len(state.tasks)


def _validate_task_bindings(
    source_name: str,
    task_ids: Any,
    children: list[dict[str, Any]],
) -> None:
    expected = set(task_ids)
    bound = {
        str(child.get("_dynamic_task_id"))
        for child in children
        if child.get("_dynamic_task_id")
    }
    completed = {
        str(child.get("_dynamic_task_id"))
        for child in children
        if child.get("_dynamic_task_id") and child.get("_dynamic_task_complete")
    }
    missing_bindings = sorted(expected - bound)
    missing_completion = sorted(expected - completed)
    if missing_bindings:
        raise RunnerError(
            f"Stage {source_name} tasks have no child Stage bindings: "
            + ", ".join(missing_bindings)
        )
    if missing_completion:
        raise RunnerError(
            f"Stage {source_name} tasks have no completion Stage: "
            + ", ".join(missing_completion)
        )


def _expand_stages(
    value: Any,
    source_name: str,
    group: str,
    path: list[str],
    *,
    result_kind: str,
    task_id_map: dict[str, str],
    reserved_names: set[str],
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
        apply_ai_profile_defaults(definition)
        if any(str(key).startswith("_dynamic_") for key in definition):
            raise RunnerError(
                f"stages[{index}] contains Runner-owned dynamic metadata"
            )
        task_id = str(definition.pop("task_id", "") or "")
        if task_id:
            task_id = task_id_map.get(task_id, task_id)
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

    local_set = set(local_names)
    for definition in clean:
        for status, target in (definition.get("routes") or {}).items():
            if target not in {"next", "done", "stop"} and target not in local_set:
                raise RunnerError(
                    f"dynamic Stage {source_name} child {definition['name']} "
                    f"routes.{status} must stay inside the child Workflow"
                )
        for target in definition.get("targets") or []:
            if target not in local_set:
                raise RunnerError(
                    f"dynamic Stage {source_name} child {definition['name']} "
                    f"handoff target must stay inside the child Workflow"
                )

    name_map = {
        name: f"{group}__{_safe_name(name)}"
        for name in local_names
    }
    collisions = sorted(set(name_map.values()) & reserved_names)
    if collisions:
        raise RunnerError(
            f"dynamic Stage {source_name} child names collide with parent Workflow: "
            + ", ".join(collisions)
        )
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
