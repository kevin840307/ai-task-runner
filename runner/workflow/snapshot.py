"""Durable Workflow resource snapshot used by one long-running Run."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..errors import RunnerError
from ..resources import text_hash, write_text
from .schema import validate_stage, validate_topology

SNAPSHOT_FILE = "workflow.snapshot.json"
RESOURCE_DIR = "resources"


def snapshot_path(project_root: str | Path, work_dir: str | Path) -> Path:
    return Path(project_root).resolve() / work_dir / SNAPSHOT_FILE


def load_snapshot(project_root: str | Path, work_dir: str | Path) -> list[dict[str, Any]] | None:
    path = snapshot_path(project_root, work_dir)
    if not path.is_file():
        return None
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunnerError(f"invalid workflow snapshot: {path}: {error}") from error
    _validate_snapshot(workflow)
    return workflow


def freeze_workflow(
    workflow: list[dict[str, Any]],
    project_root: str | Path,
    work_dir: str | Path,
) -> list[dict[str, Any]]:
    """Snapshot resolved prompt files and persist the normalized Workflow."""
    work = Path(project_root).resolve() / work_dir
    frozen = deepcopy(workflow)
    _snapshot_prompts(frozen, work / RESOURCE_DIR)
    payload = json.dumps(frozen, ensure_ascii=False, indent=2, sort_keys=True)
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
        if path.is_absolute() and path.is_file():
            try:
                text = path.read_text(encoding="utf-8-sig")
            except OSError as error:
                raise RunnerError(f"cannot snapshot prompt: {path}: {error}") from error
            target = resources / f"{text_hash(text)}{path.suffix or '.txt'}"
            if not target.is_file():
                write_text(target, text)
            value["prompt"] = str(target.resolve())
    for child in value.values():
        _snapshot_prompts(child, resources)


def _validate_snapshot(workflow: Any) -> None:
    if not isinstance(workflow, list) or not workflow:
        raise RunnerError("workflow snapshot must be a non-empty list")

    def visit(items: list[Any]) -> None:
        for item in items:
            if not isinstance(item, dict):
                raise RunnerError("workflow snapshot contains an invalid Stage")
            values = {
                key: value
                for key, value in item.items()
                if key not in {"_workflow_index", "_task_index", "_task_last"}
            }
            validate_stage(str(item.get("name", "")), values)
            recover = item.get("recover")
            if isinstance(recover, list):
                visit(recover)
            planner = item.get("planner_stages")
            if isinstance(planner, dict):
                visit(list(planner.values()))

    visit(workflow)
    validate_topology(workflow)


__all__ = ["RESOURCE_DIR", "SNAPSHOT_FILE", "freeze_workflow", "load_snapshot", "snapshot_path"]
