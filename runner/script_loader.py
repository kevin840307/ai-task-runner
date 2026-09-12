"""Load YAML batch items and translate them into canonical runner fields."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .utils.files import io_path
from .errors import RunnerError
from .plugins.registry import merge_plugin_config, plugin_config_from_yaml



# Per-item overrides intentionally mirror task-scoped CLI options. Batch orchestration
# controls (script/work_dir/resume/force_new/plan_only/output mode) stay outer-run only
# so durable YAML child state remains <work_dir>/script/<index>.
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
    "api_wait_timeout": "api_retry_timeout",
    "watchdog_interval": "watchdog_interval",
    "max_attempts": "same_session_retries",
    "review_retries": "review_retries",
    "max_cycles": "max_cycles",
    "retry_delay": "stage_retry_delay",
    "retry_wait": "api_retry_wait",
    "retry_max_wait": "api_retry_max_wait",
    "final_ai_validations": "final_ai_validations",
    "ai_validator_count": "final_ai_validations",
    "final_ai_required_passes": "final_ai_required_passes",
    "ai_validator_required_passes": "final_ai_required_passes",
}

def _string_value(item: dict[str, Any], index: int, field_name: str) -> str:
    value = item.get(field_name, "")
    if not isinstance(value, str):
        raise RunnerError(f"script item {index} {field_name} must be a string")
    return value.strip()


def _read_item_file(
    script: Path, item: dict[str, Any], index: int, field_name: str,
    encoding: str = "utf-8", *, allow_missing: bool = False,
) -> tuple[str, str] | None:
    value = item.get(field_name)
    if not value:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RunnerError(f"script item {index} {field_name} must be a non-empty string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = script.parent / path
    try:
        return io_path(path).read_text(encoding=encoding), str(path.resolve())
    except OSError as error:
        if allow_missing:
            return "", str(path.resolve())
        raise RunnerError(f"script item {index} {field_name} not found: {value}") from error


def _goal(
    script: Path, item: dict[str, Any], index: int, *, allow_missing: bool = False,
) -> tuple[str, str | None]:
    goal = item.get("prompt") or item.get("goal")
    goal_file = item.get("goal_file")
    if goal and goal_file:
        raise RunnerError(f"script item {index} must use either prompt or goal_file, not both")
    loaded = _read_item_file(script, item, index, "goal_file", allow_missing=allow_missing)
    if loaded:
        goal, goal_file = loaded
    if not isinstance(goal, str) or (not goal.strip() and not (allow_missing and goal_file)):
        raise RunnerError(f"script item {index} requires prompt or goal_file")
    return goal.strip(), goal_file


def _ai_validator_prompt(
    script: Path, item: dict[str, Any], index: int, *, allow_missing: bool = False,
) -> tuple[str, str | None]:
    prompt = _string_value(item, index, "ai_validator_prompt")
    prompt_file = item.get("ai_validator_prompt_file")
    if prompt and prompt_file:
        raise RunnerError(
            f"script item {index} must use either ai_validator_prompt or ai_validator_prompt_file, not both"
        )
    loaded = _read_item_file(
        script, item, index, "ai_validator_prompt_file", "utf-8-sig",
        allow_missing=allow_missing,
    )
    if loaded:
        prompt, prompt_file = loaded
    return prompt.strip(), prompt_file


def _options(script: Path, item: dict[str, Any], index: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "project_root" in item:
        value = item["project_root"]
        if not isinstance(value, str) or not value.strip():
            raise RunnerError(f"script item {index} project_root must be a non-empty string")
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


def _parse_item(
    script: Path, item: Any, index: int, *, allow_missing_files: bool = False,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise RunnerError(f"script item {index} must be an object")
    goal, goal_file = _goal(script, item, index, allow_missing=allow_missing_files)
    validator = item.get("validator")
    explicit_workflow = bool(item.get("workflow_file") or item.get("workflow"))
    if validator is None and explicit_workflow:
        validator = ""
    if not isinstance(validator, str) or (not validator.strip() and not explicit_workflow):
        raise RunnerError(
            f"script item {index} requires validator path/'ai' unless it supplies a workflow"
        )
    ai_prompt, ai_prompt_file = _ai_validator_prompt(
        script, item, index, allow_missing=allow_missing_files
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


def load_yaml_script(
    path: Path, *, allow_missing_files: bool = False,
) -> list[dict[str, Any]]:
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


__all__ = ["load_yaml_script"]
