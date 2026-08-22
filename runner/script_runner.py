"""YAML batch mode orchestration."""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .config import RuntimeConfig
from .errors import RunnerError
from .version import __version__


ExecuteOne = Callable[[RuntimeConfig], int]


def _read_item_file(
    script: Path,
    item: dict[str, Any],
    index: int,
    field_name: str,
    encoding: str = "utf-8",
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
        return path.read_text(encoding=encoding), str(path.resolve())
    except OSError as error:
        raise RunnerError(
            f"script item {index} {field_name} not found: {value}"
        ) from error


def load_yaml_script(path: Path) -> list[dict[str, Any]]:
    try:
        import yaml
    except ImportError as error:
        raise RunnerError(
            "YAML script requires PyYAML: pip install PyYAML"
        ) from error

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise RunnerError(f"invalid YAML script: {error}") from error

    if not isinstance(data, list) or not data:
        raise RunnerError("YAML script must be a non-empty array")

    items: list[dict[str, Any]] = []
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise RunnerError(f"script item {index} must be an object")
        prompt = item.get("prompt") or item.get("goal")
        goal_file = item.get("goal_file")
        validator = item.get("validator")
        if prompt and goal_file:
            raise RunnerError(
                f"script item {index} must use either prompt or goal_file, not both"
            )
        goal_input = _read_item_file(path, item, index, "goal_file")
        if goal_input:
            prompt, goal_file = goal_input
        if not isinstance(prompt, str) or not prompt.strip():
            raise RunnerError(f"script item {index} requires prompt or goal_file")
        if not isinstance(validator, str) or not validator.strip():
            raise RunnerError(
                f"script item {index} requires validator path or 'ai'"
            )
        ai_prompt = item.get("ai_validator_prompt", "")
        ai_prompt_file = item.get("ai_validator_prompt_file")
        if ai_prompt and ai_prompt_file:
            raise RunnerError(
                f"script item {index} must use either ai_validator_prompt or ai_validator_prompt_file, not both"
            )
        ai_prompt_input = _read_item_file(
            path,
            item,
            index,
            "ai_validator_prompt_file",
            "utf-8-sig",
        )
        if ai_prompt_input:
            ai_prompt, ai_prompt_file = ai_prompt_input
        if not isinstance(ai_prompt, str):
            raise RunnerError(f"script item {index} ai_validator_prompt must be a string")
        result = {
            "prompt": prompt.strip(),
            "validator": validator.strip(),
            "validator_prompt": str(item.get("validator_prompt", "")),
            "ai_validator_prompt": ai_prompt.strip(),
        }
        if ai_prompt_file:
            result["ai_validator_prompt_file"] = ai_prompt_file
        if goal_file:
            result["goal_file"] = goal_file
        if "project_root" in item:
            project_root = item["project_root"]
            if not isinstance(project_root, str) or not project_root.strip():
                raise RunnerError(
                    f"script item {index} project_root must be a non-empty string"
                )
            result["project_root"] = project_root.strip()
        if "loop_context_compress" in item:
            value = item["loop_context_compress"]
            if not isinstance(value, bool):
                raise RunnerError(f"script item {index} loop_context_compress must be a boolean")
            result["loop_context_compress"] = value
        if "loop_context_compress_threshold" in item:
            value = item["loop_context_compress_threshold"]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 100:
                raise RunnerError(f"script item {index} loop_context_compress_threshold must be between 0 and 100")
            result["loop_context_compress_threshold"] = float(value)
        for name in ("ai_validator_count", "ai_validator_required_passes"):
            if name in item:
                value = item[name]
                if not isinstance(value, int) or value < 0:
                    raise RunnerError(
                        f"script item {index} {name} must be a non-negative integer"
                    )
                result[name] = value
        items.append(result)
    return items


def execute_script(args: RuntimeConfig, execute_one: ExecuteOne) -> int:
    script = Path(args.script).resolve()
    if not script.is_file():
        raise RunnerError("invalid YAML script")

    items = load_yaml_script(script)
    total = len(items)
    for index, item in enumerate(items, 1):
        script_event(args, "script.item_started", index, total, item)
        child = script_item_args(args, item, index)
        child.script_index = index
        child.script_total = total
        code = execute_one(child)
        if code != 0:
            script_event(
                args,
                "script.item_failed",
                index,
                total,
                item,
                exit_code=code,
            )
            return code
        script_event(args, "script.item_completed", index, total, item)
    return 0


def script_event(
    args: RuntimeConfig,
    event_type: str,
    index: int,
    total: int,
    item: dict[str, Any],
    exit_code: int | None = None,
) -> None:
    event: dict[str, Any] = {
        "schema_version": 1,
        "runner_version": __version__,
        "type": event_type,
        "timestamp": time.time(),
        "script_index": index,
        "script_total": total,
        "prompt_preview": item["prompt"][:500],
    }
    if exit_code is not None:
        event["exit_code"] = exit_code

    callback = getattr(args, "event_callback", None)
    if callback is not None:
        try:
            callback(event)
        except Exception:
            # External UI/skill failures must not stop script execution.
            pass
    if getattr(args, "json_events", False):
        try:
            print(json.dumps(event), flush=True)
        except (BrokenPipeError, OSError):
            args.json_events = False
        return
    if not getattr(args, "human_output", True):
        return

    if event_type == "script.item_started":
        print(f"[Script {index}/{total}] {item['prompt']}", flush=True)
    elif event_type == "script.item_completed":
        print(f"[Script {index}/{total}] PASS", flush=True)
    else:
        print(
            f"[Script {index}/{total}] FAILED ({exit_code})",
            file=sys.stderr,
            flush=True,
        )


def script_item_args(
    args: RuntimeConfig,
    item: dict[str, Any],
    index: int,
) -> RuntimeConfig:
    child = copy.copy(args)
    child.script = None
    child.goal = item["prompt"]
    child.goal_file = item.get("goal_file")
    item_root = Path(item["project_root"]) if "project_root" in item else Path(args.project_root)
    if "project_root" in item and not item_root.is_absolute():
        item_root = Path(args.project_root) / item_root
    child.project_root = str(item_root.resolve())
    child.validator = item["validator"]
    child.validator_prompt = item["validator_prompt"]
    child.ai_validator_prompt = item.get("ai_validator_prompt", "")
    child.ai_validator_prompt_file = item.get("ai_validator_prompt_file")
    child.final_ai_validations = item.get(
        "ai_validator_count", child.final_ai_validations
    )
    child.final_ai_required_passes = item.get(
        "ai_validator_required_passes", child.final_ai_required_passes
    )
    child.loop_context_compress = item.get(
        "loop_context_compress", getattr(child, "loop_context_compress", False)
    )
    child.loop_context_compress_threshold = item.get(
        "loop_context_compress_threshold", getattr(child, "loop_context_compress_threshold", 50.0)
    )
    if child.final_ai_validations < 1:
        raise RunnerError(f"script item {index} ai_validator_count must be positive")
    if not 0 <= child.final_ai_required_passes <= child.final_ai_validations:
        raise RunnerError(
            f"script item {index} ai_validator_required_passes must be 0 or <= ai_validator_count"
        )
    child.work_dir = str(Path(args.work_dir) / "script" / f"{index:03d}")

    state_file = (
        Path(child.project_root)
        / child.work_dir
        / "state.json"
    )
    child.resume = bool(args.resume and state_file.is_file())
    child.force_new = not child.resume
    return child
