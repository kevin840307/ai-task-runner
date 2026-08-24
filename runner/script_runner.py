"""Execute validated YAML batch script items."""
from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import RuntimeConfig
from .errors import ConfigurationError, RunnerError
from .plugins.registry import merge_plugin_config
from .script_loader import load_yaml_script
from .version import __version__

ExecuteOne = Callable[[RuntimeConfig], int]


def execute_script(args: RuntimeConfig, execute_one: ExecuteOne) -> int:
    script = Path(args.script).resolve()
    if not script.is_file():
        raise ConfigurationError("invalid YAML script")

    try:
        items = load_yaml_script(script)
    except RunnerError as error:
        raise ConfigurationError(str(error)) from error
    total = len(items)
    for index, item in enumerate(items, 1):
        _emit_script_event(args, "script.item_started", index, total, item)
        child = replace(
            build_script_item_config(args, item, index),
            script_index=index,
            script_total=total,
        )
        code = execute_one(child)
        if code != 0:
            _emit_script_event(
                args,
                "script.item_failed",
                index,
                total,
                item,
                exit_code=code,
            )
            return code
        _emit_script_event(args, "script.item_completed", index, total, item)
    return 0


def _emit_script_event(
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
        "prompt_preview": item["goal"][:500],
    }
    if exit_code is not None:
        event["exit_code"] = exit_code

    callback = getattr(args, "event_callback", None)
    if callback is not None:
        try:
            callback(event)
        except Exception:  # noqa: BLE001, S110 - callback failures are isolated
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
        print(f"[Script {index}/{total}] {item['goal']}", flush=True)
    elif event_type == "script.item_completed":
        print(f"[Script {index}/{total}] PASS", flush=True)
    else:
        print(
            f"[Script {index}/{total}] FAILED ({exit_code})",
            file=sys.stderr,
            flush=True,
        )


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
    child = replace(
        args,
        script=None,
        goal=item["goal"],
        goal_file=item.get("goal_file"),
        project_root=project_root,
        validator=item["validator"],
        validator_prompt=item["validator_prompt"],
        ai_validator_prompt=item.get("ai_validator_prompt", ""),
        ai_validator_prompt_file=item.get("ai_validator_prompt_file"),
        review_retries=item.get("review_retries", args.review_retries),
        final_ai_validations=item.get("final_ai_validations", args.final_ai_validations),
        final_ai_required_passes=item.get(
            "final_ai_required_passes", args.final_ai_required_passes
        ),
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
