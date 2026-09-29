"""Shared Workflow result, task, and durable snapshot helpers."""
from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..ai.structured_output import (
    AIValidationResult,
    ReviewResult,
    parse_result,
    require_object,
    require_text,
    require_text_list,
)
from ..config.defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS
from ..errors import ConfigurationError, RunnerError
from ..resources import text_hash, write_text
from ..runtime import events as progress
from ..runtime.run_state import RunState, Task
from ..utils import bounded_text, io_path
from .schema import validate_stage, validate_topology
from .stages.contracts import StageContext, StageResult

MAX_MISSING_ITEMS = 100
MAX_MISSING_ITEM_CHARS = 1_000
MAX_REASON_CHARS = 4_000

SNAPSHOT_FILE = "workflow.snapshot.json"
RESOURCE_DIR = "resources"
RUN_RESOURCE_FILES = {
    "goal": "goal.txt",
    "ai_validator_prompt": "ai-validator-prompt.txt",
}


def decode_tasks(value: Any, *, cycle: int, minimum: int = 1) -> list[Task]:
    if isinstance(value, list) and all(isinstance(item, Task) for item in value):
        tasks = list(value)
        if len(tasks) < minimum:
            raise RunnerError(f"tasks must contain at least {minimum} items")
        return tasks
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise RunnerError(
                f"task producer must return valid JSON: {error}"
            ) from error
    if isinstance(value, dict):
        raw = value.get("tasks")
    elif isinstance(value, list):
        raw = value
    else:
        raise RunnerError("model JSON task result must be an object or array")
    if not isinstance(raw, list) or len(raw) < minimum:
        raise RunnerError(f"tasks must contain at least {minimum} items")

    tasks: list[Task] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise RunnerError(f"tasks[{index}] must be an object")
        tasks.append(Task(
            id=f"c{cycle:02d}-t{index:03d}",
            title=require_text(item.get("title"), f"tasks[{index}].title"),
            description=require_text(
                item.get("description"),
                f"tasks[{index}].description",
            ),
            deliverable=require_text(
                item.get("deliverable"),
                f"tasks[{index}].deliverable",
            ),
            acceptance_criteria=require_text_list(
                item.get("acceptance_criteria", item.get("accept_criteria")),
                f"tasks[{index}].acceptance_criteria",
                allow_empty=False,
            ),
        ))
    return tasks


def _decision(
    value: Any,
    *,
    flag: str,
    prefix: str,
) -> tuple[bool, str, list[str]]:
    value = require_object(value)
    verdict = value.get(flag)
    if not isinstance(verdict, bool):
        raise RunnerError(f"{prefix}.{flag} must be boolean")
    missing = [
        item[:MAX_MISSING_ITEM_CHARS]
        for item in require_text_list(
            value.get("missing_items", []),
            f"{prefix}.missing_items",
        )[:MAX_MISSING_ITEMS]
    ]
    if verdict == bool(missing):
        state = "passed/completed" if verdict else "failed"
        expected = "empty" if verdict else "non-empty"
        raise RunnerError(
            f"{state} {prefix} must have {expected} missing_items"
        )
    reason = require_text(value.get("reason"), f"{prefix}.reason")[:MAX_REASON_CHARS]
    return verdict, reason, missing


def parse_review(text: str, ctx: StageContext) -> ReviewResult:
    def parse(value: Any) -> ReviewResult:
        completed, reason, missing = _decision(
            value,
            flag="completed",
            prefix="review",
        )
        return {
            "completed": completed,
            "reason": reason,
            "missing_items": missing,
        }

    return parse_result(text, parse)


def parse_ai_validation(
    text: str,
    ctx: StageContext | None = None,
) -> AIValidationResult:
    def parse(value: Any) -> AIValidationResult:
        obj = require_object(value)
        passed, reason, missing = _decision(
            obj,
            flag="passed",
            prefix="validator",
        )
        return {
            "passed": passed,
            "reason": reason,
            "missing_items": missing,
            "checks_run": require_text_list(
                obj.get("checks_run", []),
                "validator.checks_run",
            )[:MAX_MISSING_ITEMS],
            "suggested_checks": require_text_list(
                obj.get("suggested_checks", []),
                "validator.suggested_checks",
            )[:MAX_MISSING_ITEMS],
        }

    return parse_result(text, parse)


PARSERS = {
    "review": parse_review,
    "validation": parse_ai_validation,
}


def reduce_result(ctx: StageContext, result: StageResult) -> StageResult:
    if result.kind == "tasks":
        return _reduce_tasks(ctx, result)
    if result.kind == "task":
        return _reduce_task(ctx, result)
    if result.kind == "review":
        return _reduce_review(ctx, result)
    if result.kind == "validation":
        return _reduce_validation(ctx, result)
    return result


def _reduce_tasks(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status != "pass":
        return result
    source = result.data if result.data is not None else result.output
    tasks = decode_tasks(source, cycle=ctx.state.cycle)
    install_plan(ctx.state, tasks, ctx.ai_client.session_id)
    progress.show_todo(ctx.state)
    return result


def _reduce_task(ctx: StageContext, result: StageResult) -> StageResult:
    task = ctx.task
    if task is None:
        ctx.save_session()
        return result
    task.attempts += 1
    task.changed_files = list(
        dict.fromkeys([*task.changed_files, *result.changed_files])
    )
    task.last_output = bounded_text(
        result.output
        if result.status == "pass"
        else str(result.error or result.output),
        MAX_TASK_OUTPUT_CHARS,
    )
    ctx.save_session()
    return result


def _reduce_review(ctx: StageContext, result: StageResult) -> StageResult:
    task = ctx.task
    if task is not None and isinstance(result.data, dict):
        task.last_review = result.data
    if result.status == "pass":
        ctx.scratch.pop("review_client", None)
        progress.set_status(
            "Review PASS",
            task.title if task else result.stage,
        )
    elif result.status == "fail":
        progress.set_status(
            "Review 未通過，依 routes 返回",
            result.output,
        )
    return result


def _reduce_validation(ctx: StageContext, result: StageResult) -> StageResult:
    if result.status in {"pass", "fail"}:
        ctx.state.validator_output = bounded_text(
            result.output,
            MAX_VALIDATOR_OUTPUT_CHARS,
        )
        if result.status == "fail":
            ctx.set_stage("validator_failed", result.output)
            progress.set_status("驗證失敗，依 routes 處理", result.stage)
    return result


def install_plan(
    state: RunState,
    tasks: Sequence[Task],
    session_id: str,
) -> None:
    state.ai_session_id = session_id
    state.tasks = list(tasks)
    state.current = 0
    state.completed = False


def finish_task(ctx: StageContext) -> None:
    state = ctx.state
    if state.current >= len(state.tasks):
        raise ConfigurationError("task-scoped workflow has no pending task")
    task = state.tasks[state.current]
    task.status = "completed"
    task.last_output = ""
    state.ai_session_id = ctx.ai_client.session_id
    state.current += 1
    progress.set_status("任務完成", task.title)


def finish_run(ctx: StageContext) -> None:
    if any(task.status != "completed" for task in ctx.state.tasks):
        raise ConfigurationError("workflow ended with pending planned tasks")
    ctx.state.ai_session_id = ""
    ctx.state.transition_previous = {}
    ctx.state.completed = True
    ctx.ai_client.session_id = ""
    ctx.set_stage("completed", "")
    progress.set_status("全部完成", "Workflow PASS")


def snapshot_path(project_root: str | Path, work_dir: str | Path) -> Path:
    return Path(project_root).resolve() / work_dir / SNAPSHOT_FILE


def load_snapshot(
    project_root: str | Path,
    work_dir: str | Path,
) -> list[dict[str, Any]] | None:
    path = snapshot_path(project_root, work_dir)
    if not io_path(path).is_file():
        return None
    try:
        workflow = json.loads(io_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(
            f"invalid workflow snapshot: {path}: {error}"
        ) from error
    try:
        _validate_snapshot(workflow)
    except RunnerError as error:
        raise ConfigurationError(
            f"invalid workflow snapshot: {path}: {error}"
        ) from error
    return workflow


def run_resource_path(
    project_root: str | Path,
    work_dir: str | Path,
    name: str,
) -> Path:
    try:
        filename = RUN_RESOURCE_FILES[name]
    except KeyError as error:
        raise ValueError(f"unknown run resource: {name}") from error
    return (
        Path(project_root).resolve()
        / work_dir
        / RESOURCE_DIR
        / filename
    )


def load_run_resource(
    project_root: str | Path,
    work_dir: str | Path,
    name: str,
) -> tuple[str, str] | None:
    path = run_resource_path(project_root, work_dir, name)
    if not io_path(path).is_file():
        return None
    try:
        return (
            str(path.resolve()),
            io_path(path).read_text(encoding="utf-8-sig"),
        )
    except OSError as error:
        raise ConfigurationError(
            f"cannot read run resource: {path}: {error}"
        ) from error


def freeze_run_resource(
    source: str | Path | None,
    project_root: str | Path,
    work_dir: str | Path,
    name: str,
) -> tuple[str, str] | None:
    if not source:
        return None
    path = Path(source).expanduser()
    try:
        text = io_path(path).read_text(encoding="utf-8-sig")
    except OSError as error:
        raise ConfigurationError(
            f"cannot snapshot {name}: {path}: {error}"
        ) from error
    target = run_resource_path(project_root, work_dir, name)
    write_text(target, text)
    return str(target.resolve()), text


def freeze_workflow(
    workflow: list[dict[str, Any]],
    project_root: str | Path,
    work_dir: str | Path,
) -> list[dict[str, Any]]:
    work = Path(project_root).resolve() / work_dir
    frozen = deepcopy(workflow)
    _snapshot_prompts(frozen, work / RESOURCE_DIR)
    payload = json.dumps(
        frozen,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    write_text(work / SNAPSHOT_FILE, payload)
    return frozen


def _snapshot_prompts(value: Any, resources: Path) -> None:
    if isinstance(value, list):
        for item in value:
            _snapshot_prompts(item, resources)
        return
    if not isinstance(value, dict):
        return
    prompt = value.get("prompt")
    if isinstance(prompt, str):
        path = Path(prompt).expanduser()
        if path.is_absolute() and io_path(path).is_file():
            try:
                text = io_path(path).read_text(encoding="utf-8-sig")
            except OSError as error:
                raise RunnerError(
                    f"cannot snapshot prompt: {path}: {error}"
                ) from error
            target = resources / f"{text_hash(text)}{path.suffix or '.txt'}"
            if not io_path(target).is_file():
                write_text(target, text)
            value["prompt"] = str(target.resolve())
    for child in value.values():
        _snapshot_prompts(child, resources)


def _validate_snapshot(workflow: Any) -> None:
    if not isinstance(workflow, list) or not workflow:
        raise RunnerError("workflow snapshot must be a non-empty list")
    for item in workflow:
        if not isinstance(item, dict):
            raise RunnerError("workflow snapshot contains an invalid Stage")
        values = {
            key: value
            for key, value in item.items()
            if key != "_workflow_index"
        }
        validate_stage(str(item.get("name", "")), values)
    validate_topology(workflow)


__all__ = [
    "PARSERS",
    "RESOURCE_DIR",
    "SNAPSHOT_FILE",
    "decode_tasks",
    "finish_run",
    "finish_task",
    "freeze_run_resource",
    "freeze_workflow",
    "load_run_resource",
    "load_snapshot",
    "parse_ai_validation",
    "parse_review",
    "reduce_result",
    "run_resource_path",
    "snapshot_path",
]
