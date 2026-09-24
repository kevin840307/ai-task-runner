"""Execute validated YAML batch script items."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .config.runtime import RuntimeConfig
from .errors import ConfigurationError, RunnerError
from .plugins.registry import merge_plugin_config
from .runtime import events
from .runtime.run_state import StateStore
from .script_loader import load_yaml_script
from .workflow.loader import load_default_workflow, load_workflow
from .workflow.snapshot import load_run_resource, load_snapshot

ExecuteOne = Callable[[RuntimeConfig], int]


SCRIPT_ITEM_RUNTIME_FIELDS = frozenset({
    "backend", "command", "sandbox", "agent_args", "validator_args",
    "protect_files", "validator_timeout", "agent_timeout", "planning_timeout",
    "agent_idle_after_change_timeout", "api_retry_timeout", "watchdog_interval",
    "same_session_retries", "review_retries", "max_cycles", "stage_retry_delay",
    "api_retry_wait", "api_retry_max_wait", "final_ai_validations",
    "final_ai_required_passes", "ai_validator_yolo", "readonly_safety",
})


def _runtime_overrides(item: dict[str, Any]) -> dict[str, Any]:
    return {name: item[name] for name in SCRIPT_ITEM_RUNTIME_FIELDS if name in item}


def execute_script(args: RuntimeConfig, execute_one: ExecuteOne) -> int:
    script = Path(args.script).resolve()
    if not script.is_file():
        raise ConfigurationError("invalid YAML script")

    try:
        items = load_yaml_script(script, allow_missing_files=args.resume)
    except RunnerError as error:
        raise ConfigurationError(str(error)) from error
    total = len(items)
    for index, item in enumerate(items, 1):
        child = replace(
            build_script_item_config(args, item, index),
            script_index=index,
            script_total=total,
        )
        marker = _skip_marker(child)
        if not args.resume:
            try:
                marker.unlink()
            except FileNotFoundError:
                pass
        elif marker.is_file():
            if item.get("skip_on_max_cycles") is True and _valid_skip_marker(marker, item):
                _emit_script_event(
                    "script.item_skipped", index, total, item, child=child,
                    reason="previously skipped after max cycles",
                )
                continue
            # A marker from a previous YAML definition must never become valid
            # again after configuration changes. Remove it before executing.
            try:
                marker.unlink()
            except FileNotFoundError:
                pass

        _emit_script_event("script.item_started", index, total, item, child=child)
        try:
            code = execute_one(child)
        except ConfigurationError as error:
            if item.get("skip_on_max_cycles") is True and _is_max_cycles_error(error):
                _write_skip_marker(marker, child, item, str(error))
                _emit_script_event(
                    "script.item_skipped", index, total, item, child=child, reason=str(error)
                )
                continue
            raise
        if code == 0 and not _child_completed(child, item):
            # A child can exit cleanly after saving resumable, unfinished state.
            # Batch orchestration must not report that as a completed script item.
            code = 1
        if code != 0:
            _emit_script_event(
                "script.item_failed",
                index,
                total,
                item,
                child=child,
                exit_code=code,
            )
            return code
        _emit_script_event("script.item_completed", index, total, item, child=child)
    return 0


def _skip_marker(child: RuntimeConfig) -> Path:
    return Path(child.project_root) / child.work_dir / "script-item-skipped.json"


def _is_max_cycles_error(error: BaseException) -> bool:
    return str(error).strip().lower().startswith("max cycles reached:")


def _script_item_fingerprint(item: dict[str, Any]) -> str:
    payload = json.dumps(
        item,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _valid_skip_marker(path: Path, item: dict[str, Any]) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(data, dict)
        and data.get("item_fingerprint") == _script_item_fingerprint(item)
    )


def _write_skip_marker(
    path: Path,
    child: RuntimeConfig,
    item: dict[str, Any],
    reason: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "reason": reason,
        "max_cycles": child.max_cycles,
        "script_index": child.script_index,
        "script_total": child.script_total,
        "item_fingerprint": _script_item_fingerprint(item),
    }
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _child_completed(child: RuntimeConfig, item: dict[str, Any]) -> bool:
    if item.get("skip_on_max_cycles") is True and _valid_skip_marker(_skip_marker(child), item):
        return True
    state_path = Path(child.project_root) / child.work_dir / "state.json"
    store = StateStore(Path(child.project_root), state_path.parent)
    try:
        _, state = store._read_state(state_path, strict=True)  # noqa: SLF001
    except ConfigurationError:
        return False
    return state is not None and state.completed and state.stage == "completed"


def _emit_script_event(
    event_type: str,
    index: int,
    total: int,
    item: dict[str, Any],
    *,
    child: RuntimeConfig | None = None,
    exit_code: int | None = None,
    reason: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "script_index": index,
        "script_total": total,
        "prompt_preview": item["goal"][:500],
    }
    if child is not None:
        payload["child_project_root"] = child.project_root
        payload["child_work_dir"] = child.work_dir
    if exit_code is not None:
        payload["exit_code"] = exit_code
    if reason:
        payload["reason"] = reason
    events.publish(event_type, event_type.rsplit("_", 1)[-1], **payload)


def build_script_item_config(
    args: RuntimeConfig,
    item: dict[str, Any],
    index: int,
) -> RuntimeConfig:
    item_root = Path(item["project_root"]) if "project_root" in item else Path(args.project_root)
    if "project_root" in item and not item_root.is_absolute():
        item_root = Path(args.project_root) / item_root
    work_dir = str(Path(args.work_dir) / "script" / f"{index:03d}")
    project_root = str(item_root.resolve())
    resume = bool(args.resume and Path(project_root, work_dir, "state.json").is_file())
    frozen_goal = load_run_resource(project_root, work_dir, "goal") if resume else None
    frozen_ai_prompt = (
        load_run_resource(project_root, work_dir, "ai_validator_prompt") if resume else None
    )
    goal = frozen_goal[1] if frozen_goal is not None else item["goal"]
    goal_file = frozen_goal[0] if frozen_goal is not None else item.get("goal_file")
    ai_validator_prompt = (
        frozen_ai_prompt[1]
        if frozen_ai_prompt is not None
        else item.get("ai_validator_prompt", "")
    )
    ai_validator_prompt_file = (
        frozen_ai_prompt[0]
        if frozen_ai_prompt is not None
        else item.get("ai_validator_prompt_file")
    )
    frozen = load_snapshot(project_root, work_dir) if resume else None
    workflow, workflow_explicit = (
        (frozen, True)
        if frozen is not None
        else select_script_workflow(args, item, ai_validator_prompt)
    )
    child = replace(
        args,
        script=None,
        goal=goal,
        goal_file=goal_file,
        project_root=project_root,
        project_name=item.get("project_name", args.project_name),
        validator=item.get("validator") or args.validator,
        validator_prompt=item.get("validator_prompt", ""),
        ai_validator_prompt=ai_validator_prompt,
        ai_validator_prompt_file=ai_validator_prompt_file,
        **_runtime_overrides(item),
        workflow=workflow,
        workflow_explicit=workflow_explicit,
        plugins=merge_plugin_config(args.plugins, item.get("plugins", {})),
        work_dir=work_dir,
        resume=resume,
        force_new=not resume,
    )
    try:
        child.validate()
    except ValueError as error:
        raise RunnerError(f"script item {index} {error}") from error
    return child


def select_script_workflow(
    args: RuntimeConfig,
    item: dict[str, Any],
    ai_validator_prompt: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Apply workflow precedence for one YAML List item."""
    if item.get("workflow") is not None:
        return item["workflow"], True
    if item.get("workflow_file") is not None:
        return load_workflow(item["workflow_file"]), True
    if args.workflow_explicit:
        return args.workflow, True
    return load_default_workflow(item["validator"], ai_validator_prompt), False
