"""Canonical TaskDraft / durable Task validation helpers."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DRAFT_MODES = {"auto", "single", "list"}
WORKSPACE_POLICIES = {"auto", "main", "worktree"}
_TASK_ID = re.compile(r"^task-[0-9a-f]{32}$")


def bounded_text(value: Any, label: str, limit: int, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{label} is required")
    if len(text) > limit:
        raise ValueError(f"{label} is too long")
    return text


def validate_generated_draft(
    payload: Any,
    *,
    mode: str,
    project: Path,
    workflow: str,
) -> dict[str, Any]:
    if mode not in DRAFT_MODES:
        raise ValueError("Unsupported TaskDraft mode")
    if not isinstance(payload, dict):
        raise ValueError("TaskDraft generator must return an object")
    title = bounded_text(payload.get("title"), "TaskDraft title", 240)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("TaskDraft items must be a list")
    if not raw_items:
        raise ValueError("TaskDraft must contain at least one item")
    if len(raw_items) > 32:
        raise ValueError("TaskDraft contains too many items")
    if mode == "single" and len(raw_items) != 1:
        raise ValueError("@task-single must generate exactly one item")
    if mode == "list" and len(raw_items) < 2:
        raise ValueError("@task-list must generate at least two items")

    project_path = str(project.resolve())
    workflow_path = str(workflow or "").strip()
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError(f"TaskDraft item {index + 1} must be an object")
        items.append({
            "title": bounded_text(raw.get("title"), f"TaskDraft item {index + 1} title", 240),
            "prompt": bounded_text(raw.get("prompt"), f"TaskDraft item {index + 1} prompt", 24000),
            "workflow": workflow_path,
            "project": project_path,
            "workspace": "auto",
        })
    return {
        "schema_version": 1,
        "title": title,
        "project": project_path,
        "items": items,
    }


def validate_task_draft_for_create(payload: Any, project: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("TaskDraft must be an object")
    title = bounded_text(payload.get("title"), "TaskDraft title", 240)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("TaskDraft must contain at least one item")
    if len(raw_items) > 32:
        raise ValueError("TaskDraft contains too many items")

    project_path = str(project.resolve())
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError(f"TaskDraft item {index + 1} must be an object")
        item_project = str(raw.get("project") or "").strip()
        if item_project and str(Path(item_project).expanduser().resolve()) != project_path:
            raise ValueError("TaskDraft Project does not match the selected Project")
        workspace = str(raw.get("workspace") or "auto").strip().lower()
        if workspace not in WORKSPACE_POLICIES:
            raise ValueError(f"Unsupported workspace policy: {workspace}")
        items.append({
            "title": bounded_text(raw.get("title"), f"Task item {index + 1} title", 240),
            "prompt": bounded_text(raw.get("prompt"), f"Task item {index + 1} prompt", 24000),
            "workflow": bounded_text(raw.get("workflow"), f"Task item {index + 1} Workflow", 4096),
            "project": project_path,
            "workspace": workspace,
        })
    return {
        "schema_version": 1,
        "title": title,
        "project": project_path,
        "items": items,
    }


def validate_task_id(value: str) -> str:
    task_id = str(value or "").strip()
    if not _TASK_ID.fullmatch(task_id):
        raise ValueError("Invalid Task id")
    return task_id
