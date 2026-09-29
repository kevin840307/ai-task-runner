"""YAML List loading and execution on the shared Workflow runtime."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config.runtime import RuntimeConfig
from .errors import ConfigurationError, RunnerError
from .plugins.registry import merge_plugin_config, plugin_config_from_yaml
from .runtime import events
from .runtime.run_state import StateStore
from .utils import io_path
from .workflow.lifecycle import load_run_resource, load_snapshot
from .workflow.loader import load_default_workflow, load_workflow

ExecuteOne = Callable[[RuntimeConfig], int]

SCRIPT_ITEM_RUNTIME_ALIASES = {
    "backend": "backend",
    "command": "command",
    "sandbox": "sandbox",
    "agent_args": "agent_args",
    "validator_args": "validator_args",
    "protect_files": "protect_files",
    "validator_timeout": "validator_timeout",
    "agent_timeout": "agent_timeout",
    "planning_timeout": "planning_timeout",
    "agent_idle_after_change_timeout": "agent_idle_after_change_timeout",
    "watchdog_interval": "watchdog_interval",
    "worker_hang_timeout": "worker_hang_timeout",
    "stage_retries": "stage_retries",
    "retry_delay": "retry_delay",
    "retry_max_delay": "retry_max_delay",
    "final_ai_validations": "final_ai_validations",
    "ai_validator_count": "final_ai_validations",
    "final_ai_required_passes": "final_ai_required_passes",
    "ai_validator_required_passes": "final_ai_required_passes",
    "ai_validator_yolo": "ai_validator_yolo",
    "readonly_safety": "readonly_safety",
}
SCRIPT_ITEM_RUNTIME_FIELDS = frozenset(SCRIPT_ITEM_RUNTIME_ALIASES.values())
REMOVED_SCRIPT_FIELDS = frozenset({
    "max_attempts",
    "max_cycles",
    "review_retries",
    "api_wait_timeout",
    "retry_wait",
    "retry_max_wait",
    "skip_on_max_cycles",
})


def load_yaml_script(
    path: Path,
    *,
    allow_missing_files: bool = False,
) -> list[dict[str, Any]]:
    """Load and normalize one YAML List batch file."""
    try:
        import yaml
    except ImportError as error:
        raise RunnerError("YAML script requires PyYAML: pip install PyYAML") from error
    try:
        data = yaml.safe_load(io_path(path).read_text(encoding="utf-8"))
    except Exception as error:
        raise RunnerError(f"invalid YAML script: {error}") from error
    if not isinstance(data, list) or not data:
        raise RunnerError("YAML script must be a non-empty array")
    return [
        _parse_item(path, item, index, allow_missing_files=allow_missing_files)
        for index, item in enumerate(data, 1)
    ]


def execute_script(config: RuntimeConfig, execute_one: ExecuteOne) -> int:
    """Execute each normalized YAML item through the same Runner entry."""
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
                "script.item_failed",
                index,
                total,
                item,
                child,
                exit_code=code,
            )
            return code
        _emit_script_event("script.item_completed", index, total, item, child)
    return 0


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


def _parse_item(
    script: Path,
    item: Any,
    index: int,
    *,
    allow_missing_files: bool = False,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise RunnerError(f"script item {index} must be an object")
    removed = sorted(set(item) & REMOVED_SCRIPT_FIELDS)
    if removed:
        raise RunnerError(
            f"script item {index} uses removed options: " + ", ".join(removed)
        )

    goal, goal_file = _goal(
        script,
        item,
        index,
        allow_missing=allow_missing_files,
    )
    validator = item.get("validator")
    explicit_workflow = bool(item.get("workflow_file") or item.get("workflow"))
    if validator is None and explicit_workflow:
        validator = ""
    if not isinstance(validator, str) or (
        not validator.strip() and not explicit_workflow
    ):
        raise RunnerError(
            f"script item {index} requires validator path/'ai' unless it supplies a workflow"
        )

    ai_prompt, ai_prompt_file = _ai_validator_prompt(
        script,
        item,
        index,
        allow_missing=allow_missing_files,
    )
    result = {
        "goal": goal,
        "validator": validator.strip() or None,
        "validator_prompt": _string_value(item, index, "validator_prompt"),
        "ai_validator_prompt": ai_prompt,
        **_options(script, item, index),
    }
    if ai_prompt_file:
        result["ai_validator_prompt_file"] = ai_prompt_file
    if goal_file:
        result["goal_file"] = goal_file
    return result


def _goal(
    script: Path,
    item: dict[str, Any],
    index: int,
    *,
    allow_missing: bool = False,
) -> tuple[str, str | None]:
    goal = item.get("prompt") or item.get("goal")
    goal_file = item.get("goal_file")
    if goal and goal_file:
        raise RunnerError(
            f"script item {index} must use either prompt or goal_file, not both"
        )
    loaded = _read_item_file(
        script,
        item,
        index,
        "goal_file",
        allow_missing=allow_missing,
    )
    if loaded:
        goal, goal_file = loaded
    if not isinstance(goal, str) or (
        not goal.strip() and not (allow_missing and goal_file)
    ):
        raise RunnerError(f"script item {index} requires prompt or goal_file")
    return goal.strip(), goal_file


def _ai_validator_prompt(
    script: Path,
    item: dict[str, Any],
    index: int,
    *,
    allow_missing: bool = False,
) -> tuple[str, str | None]:
    prompt = _string_value(item, index, "ai_validator_prompt")
    prompt_file = item.get("ai_validator_prompt_file")
    if prompt and prompt_file:
        raise RunnerError(
            f"script item {index} must use either ai_validator_prompt or ai_validator_prompt_file, not both"
        )
    loaded = _read_item_file(
        script,
        item,
        index,
        "ai_validator_prompt_file",
        "utf-8-sig",
        allow_missing=allow_missing,
    )
    if loaded:
        prompt, prompt_file = loaded
    return prompt.strip(), prompt_file


def _options(
    script: Path,
    item: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "project_name" in item:
        value = item["project_name"]
        if not isinstance(value, str):
            raise RunnerError(f"script item {index} project_name must be a string")
        value = " ".join(value.split())
        if len(value) > 120:
            raise RunnerError(f"script item {index} project_name is too long")
        result["project_name"] = value

    if "project_root" in item:
        value = item["project_root"]
        if not isinstance(value, str) or not value.strip():
            raise RunnerError(
                f"script item {index} project_root must be a non-empty string"
            )
        result["project_root"] = value.strip()

    configured_plugins = item.get("plugins", {})
    if not isinstance(configured_plugins, Mapping):
        raise RunnerError(f"script item {index} plugins must be an object")
    try:
        plugins = merge_plugin_config(
            plugin_config_from_yaml(item),
            configured_plugins,
        )
    except ValueError as error:
        raise RunnerError(f"script item {index} {error}") from error
    if plugins:
        result["plugins"] = plugins

    if "workflow_file" in item:
        value = item["workflow_file"]
        if not isinstance(value, str) or not value.strip():
            raise RunnerError(
                f"script item {index} workflow_file must be a non-empty string"
            )
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = script.parent / path
        result["workflow_file"] = str(path.resolve())

    seen_targets: dict[str, str] = {}
    for source, target in SCRIPT_ITEM_RUNTIME_ALIASES.items():
        if source not in item:
            continue
        previous = seen_targets.get(target)
        if previous is not None:
            raise RunnerError(
                f"script item {index} must not set both {previous} and {source}"
            )
        seen_targets[target] = source
        result[target] = item[source]

    if "workflow" in item:
        if "workflow_file" in item:
            raise RunnerError(
                f"script item {index} must use either workflow or workflow_file, not both"
            )
        from .workflow.loader import normalize_workflow

        result["workflow"] = normalize_workflow(item["workflow"], script.resolve())
    return result


def _read_item_file(
    script: Path,
    item: dict[str, Any],
    index: int,
    field_name: str,
    encoding: str = "utf-8",
    *,
    allow_missing: bool = False,
) -> tuple[str, str] | None:
    value = item.get(field_name)
    if not value:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RunnerError(
            f"script item {index} {field_name} must be a non-empty string"
        )
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = script.parent / path
    try:
        return io_path(path).read_text(encoding=encoding), str(path.resolve())
    except OSError as error:
        if allow_missing:
            return "", str(path.resolve())
        raise RunnerError(
            f"script item {index} {field_name} not found: {value}"
        ) from error


def _string_value(
    item: dict[str, Any],
    index: int,
    field_name: str,
) -> str:
    value = item.get(field_name, "")
    if not isinstance(value, str):
        raise RunnerError(
            f"script item {index} {field_name} must be a string"
        )
    return value.strip()


def _runtime_overrides(item: dict[str, Any]) -> dict[str, Any]:
    return {
        name: item[name]
        for name in SCRIPT_ITEM_RUNTIME_FIELDS
        if name in item
    }


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


__all__ = [
    "build_script_item_config",
    "execute_script",
    "load_yaml_script",
    "select_script_workflow",
]
