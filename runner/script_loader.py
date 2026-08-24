"""Load YAML batch items and translate them into canonical runner fields."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import RunnerError
from .plugins.registry import merge_plugin_config, plugin_config_from_yaml


def _string_value(item: dict[str, Any], index: int, field_name: str) -> str:
    value = item.get(field_name, "")
    if not isinstance(value, str):
        raise RunnerError(f"script item {index} {field_name} must be a string")
    return value.strip()


def _read_item_file(script: Path, item: dict[str, Any], index: int, field_name: str, encoding: str = "utf-8") -> tuple[str, str] | None:
    value = item.get(field_name)
    if not value:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RunnerError(f"script item {index} {field_name} must be a non-empty string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = script.parent / path
    try:
        return path.read_text(encoding=encoding), str(path.resolve())
    except OSError as error:
        raise RunnerError(f"script item {index} {field_name} not found: {value}") from error


def _goal(script: Path, item: dict[str, Any], index: int) -> tuple[str, str | None]:
    goal = item.get("prompt") or item.get("goal")
    goal_file = item.get("goal_file")
    if goal and goal_file:
        raise RunnerError(f"script item {index} must use either prompt or goal_file, not both")
    loaded = _read_item_file(script, item, index, "goal_file")
    if loaded:
        goal, goal_file = loaded
    if not isinstance(goal, str) or not goal.strip():
        raise RunnerError(f"script item {index} requires prompt or goal_file")
    return goal.strip(), goal_file


def _ai_validator_prompt(script: Path, item: dict[str, Any], index: int) -> tuple[str, str | None]:
    prompt = _string_value(item, index, "ai_validator_prompt")
    prompt_file = item.get("ai_validator_prompt_file")
    if prompt and prompt_file:
        raise RunnerError(
            f"script item {index} must use either ai_validator_prompt or ai_validator_prompt_file, not both"
        )
    loaded = _read_item_file(script, item, index, "ai_validator_prompt_file", "utf-8-sig")
    if loaded:
        prompt, prompt_file = loaded
    return prompt.strip(), prompt_file


def _options(item: dict[str, Any], index: int) -> dict[str, Any]:
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

    aliases = {
        "review_retries": "review_retries",
        "ai_validator_count": "final_ai_validations",
        "ai_validator_required_passes": "final_ai_required_passes",
    }
    for source, target in aliases.items():
        if source not in item:
            continue
        result[target] = item[source]
    return result


def _parse_item(script: Path, item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise RunnerError(f"script item {index} must be an object")
    goal, goal_file = _goal(script, item, index)
    validator = item.get("validator")
    if not isinstance(validator, str) or not validator.strip():
        raise RunnerError(f"script item {index} requires validator path or 'ai'")
    ai_prompt, ai_prompt_file = _ai_validator_prompt(script, item, index)
    result = {
        "goal": goal,
        "validator": validator.strip(),
        "validator_prompt": _string_value(item, index, "validator_prompt"),
        "ai_validator_prompt": ai_prompt,
        **_options(item, index),
    }
    if ai_prompt_file:
        result["ai_validator_prompt_file"] = ai_prompt_file
    if goal_file:
        result["goal_file"] = goal_file
    return result


def load_yaml_script(path: Path) -> list[dict[str, Any]]:
    try:
        import yaml
    except ImportError as error:
        raise RunnerError("YAML script requires PyYAML: pip install PyYAML") from error
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise RunnerError(f"invalid YAML script: {error}") from error
    if not isinstance(data, list) or not data:
        raise RunnerError("YAML script must be a non-empty array")
    return [_parse_item(path, item, index) for index, item in enumerate(data, 1)]


__all__ = ["load_yaml_script"]
