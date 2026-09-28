"""Execute validated YAML batch items with the same Workflow runtime."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
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
    "agent_idle_after_change_timeout", "watchdog_interval",
    "worker_hang_timeout", "stage_retries", "retry_delay", "retry_max_delay",
    "final_ai_validations",
    "final_ai_required_passes", "ai_validator_yolo", "readonly_safety",
})


def _runtime_overrides(item: dict[str, Any]) -> dict[str, Any]:
    return {name: item[name] for name in SCRIPT_ITEM_RUNTIME_FIELDS if name in item}


def execute_script(config: RuntimeConfig, execute_one: ExecuteOne) -> int:
    script = Path(config.script).resolve()
    if not script.is_file():
        raise ConfigurationError("invalid YAML script")
    try:
        items = load_yaml_script(script, allow_missing_files=config.resume)
    except RunnerError as error:
        raise ConfigurationError(str(error)) from error

    total = len(items)
    for index, item in enumerate(items, 1):
        child = replace(
            build_script_item_config(config, item, index),
            script_index=index,
            script_total=total,
        )
        _emit_script_event("script.item_started", index, total, item, child)

        code = execute_one(child)
        if code == 0 and not _child_completed(child):
            code = 1
        if code != 0:
            _emit_script_event(
                "script.item_failed", index, total, item, child, exit_code=code
            )
            return code
        _emit_script_event("script.item_completed", index, total, item, child)
    return 0


def _child_completed(child: RuntimeConfig) -> bool:
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
    child: RuntimeConfig,
    *,
    exit_code: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "script_index": index,
        "script_total": total,
        "prompt_preview": item["goal"][:500],
        "child_project_root": child.project_root,
        "child_work_dir": child.work_dir,
    }
    if exit_code is not None:
        payload["exit_code"] = exit_code
    events.publish(event_type, event_type.rsplit("_", 1)[-1], **payload)


def build_script_item_config(
    config: RuntimeConfig,
    item: dict[str, Any],
    index: int,
) -> RuntimeConfig:
    item_root = Path(item.get("project_root", config.project_root))
    if "project_root" in item and not item_root.is_absolute():
        item_root = Path(config.project_root) / item_root

    work_dir = str(Path(config.work_dir) / "script" / f"{index:03d}")
    project_root = str(item_root.resolve())
    resume = bool(
        config.resume and Path(project_root, work_dir, "state.json").is_file()
    )

    frozen_goal = load_run_resource(project_root, work_dir, "goal") if resume else None
    frozen_ai = (
        load_run_resource(project_root, work_dir, "ai_validator_prompt")
        if resume
        else None
    )
    goal = frozen_goal[1] if frozen_goal else item["goal"]
    goal_file = frozen_goal[0] if frozen_goal else item.get("goal_file")
    ai_prompt = frozen_ai[1] if frozen_ai else item.get("ai_validator_prompt", "")
    ai_prompt_file = (
        frozen_ai[0] if frozen_ai else item.get("ai_validator_prompt_file")
    )

    frozen = load_snapshot(project_root, work_dir) if resume else None
    workflow, explicit = (
        (frozen, True)
        if frozen is not None
        else select_script_workflow(config, item, ai_prompt)
    )

    child = replace(
        config,
        script=None,
        goal=goal,
        goal_file=goal_file,
        project_root=project_root,
        project_name=item.get("project_name", config.project_name),
        validator=item.get("validator") or config.validator,
        validator_prompt=item.get("validator_prompt", ""),
        ai_validator_prompt=ai_prompt,
        ai_validator_prompt_file=ai_prompt_file,
        **_runtime_overrides(item),
        workflow=workflow,
        workflow_explicit=explicit,
        plugins=merge_plugin_config(config.plugins, item.get("plugins", {})),
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
    config: RuntimeConfig,
    item: dict[str, Any],
    ai_validator_prompt: str,
) -> tuple[list[dict[str, Any]], bool]:
    if item.get("workflow") is not None:
        return item["workflow"], True
    if item.get("workflow_file") is not None:
        return load_workflow(item["workflow_file"]), True
    if config.workflow_explicit:
        return config.workflow, True
    return load_default_workflow(item["validator"], ai_validator_prompt), False
