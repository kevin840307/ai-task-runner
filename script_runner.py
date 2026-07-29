"""YAML batch mode orchestration."""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

from errors import RunnerError
from version import __version__


ExecuteOne = Callable[[argparse.Namespace], int]


def load_yaml_script(path: Path) -> list[dict[str, str]]:
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

    items: list[dict[str, str]] = []
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise RunnerError(f"script item {index} must be an object")
        prompt = item.get("prompt") or item.get("goal")
        validator = item.get("validator")
        if not isinstance(prompt, str) or not prompt.strip():
            raise RunnerError(f"script item {index} requires prompt")
        if not isinstance(validator, str) or not validator.strip():
            raise RunnerError(
                f"script item {index} requires validator path or 'ai'"
            )
        items.append(
            {
                "prompt": prompt.strip(),
                "validator": validator.strip(),
                "validator_prompt": str(item.get("validator_prompt", "")),
            }
        )
    return items


def execute_script(args: argparse.Namespace, execute_one: ExecuteOne) -> int:
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
    args: argparse.Namespace,
    event_type: str,
    index: int,
    total: int,
    item: dict[str, str],
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
    args: argparse.Namespace,
    item: dict[str, str],
    index: int,
) -> argparse.Namespace:
    child = copy.copy(args)
    child.script = None
    child.goal = item["prompt"]
    child.validator = item["validator"]
    child.validator_prompt = item["validator_prompt"]
    child.work_dir = str(Path(args.work_dir) / "script" / f"{index:03d}")

    state_file = (
        Path(args.project_root).resolve()
        / child.work_dir
        / "state.json"
    )
    child.resume = bool(args.resume and state_file.is_file())
    child.force_new = not child.resume
    return child
