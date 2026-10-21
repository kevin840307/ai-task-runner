"""Canonical TaskDraft / durable Task validation helpers."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

DRAFT_MODES = {"auto", "single", "list"}
WORKSPACE_POLICIES = {"auto", "main", "worktree"}
_TASK_ID = re.compile(r"^task-[0-9a-f]{32}$")
_ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


def bounded_text(value: Any, label: str, limit: int, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{label} is required")
    if len(text) > limit:
        raise ValueError(f"{label} is too long")
    return text


def optional_item_id(value: Any, label: str = "Task item id") -> str:
    item_id = str(value or "").strip()
    if not item_id:
        return ""
    if not _ITEM_ID.fullmatch(item_id):
        raise ValueError(f"{label} is invalid")
    return item_id


def validate_generated_draft(
    payload: Any,
    *,
    mode: str,
    project: Path,
    workflow: str,
    workflow_requirements: Callable[[Path, str], dict[str, Any]] | None = None,
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
    requirements = workflow_requirements(project, workflow_path) if workflow_requirements else {}
    if workflow_requirements is not None and requirements.get("exists") is False:
        raise ValueError("Selected Workflow does not exist")
    requires_python_validator = bool(requirements.get("requires_python_validator"))
    has_ai_validator = bool(requirements.get("has_ai_validator"))
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError(f"TaskDraft item {index + 1} must be an object")
        item = {
            "title": bounded_text(raw.get("title"), f"TaskDraft item {index + 1} title", 240),
            "prompt": bounded_text(raw.get("prompt"), f"TaskDraft item {index + 1} prompt", 24000),
            "workflow": workflow_path,
            "project": project_path,
            "workspace": "auto",
        }
        if requires_python_validator:
            item["validator"] = bounded_text(
                raw.get("validator"),
                f"TaskDraft item {index + 1} File Validator",
                4096,
                required=False,
            )
        if has_ai_validator:
            item["ai_validator_prompt_file"] = bounded_text(
                raw.get("ai_validator_prompt_file"),
                f"TaskDraft item {index + 1} AI Validator Prompt",
                4096,
                required=False,
            )
        items.append(item)
    return {
        "schema_version": 1,
        "title": title,
        "project": project_path,
        "items": items,
    }


def validate_task_draft_for_create(
    payload: Any,
    project: Path,
    *,
    workflow_requirements: Callable[[Path, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    seen_item_ids: set[str] = set()
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError(f"TaskDraft item {index + 1} must be an object")
        item_project = str(raw.get("project") or "").strip()
        if item_project and str(Path(item_project).expanduser().resolve()) != project_path:
            raise ValueError("TaskDraft Project does not match the selected Project")
        workspace = str(raw.get("workspace") or "auto").strip().lower()
        if workspace not in WORKSPACE_POLICIES:
            raise ValueError(f"Unsupported workspace policy: {workspace}")
        item_id = optional_item_id(raw.get("item_id"), f"Task item {index + 1} id")
        if item_id and item_id in seen_item_ids:
            raise ValueError("TaskDraft contains duplicate Task item ids")
        if item_id:
            seen_item_ids.add(item_id)
        workflow = bounded_text(raw.get("workflow"), f"Task item {index + 1} Workflow", 4096)
        prompt = bounded_text(raw.get("prompt"), f"Task item {index + 1} prompt", 24000, required=False)
        goal_file = bounded_text(raw.get("goal_file"), f"Task item {index + 1} goal_file", 4096, required=False)
        if not prompt and not goal_file:
            raise ValueError(f"Task item {index + 1} prompt or goal_file is required")
        if prompt and goal_file:
            raise ValueError(f"Task item {index + 1} prompt and goal_file cannot both be set")
        validator = bounded_text(raw.get("validator"), f"Task item {index + 1} File Validator", 4096, required=False)
        ai_validator_prompt = bounded_text(
            raw.get("ai_validator_prompt"),
            f"Task item {index + 1} AI Validator Prompt",
            24000,
            required=False,
        )
        ai_validator_prompt_file = bounded_text(
            raw.get("ai_validator_prompt_file"),
            f"Task item {index + 1} AI Validator Prompt file",
            4096,
            required=False,
        )
        if ai_validator_prompt and ai_validator_prompt_file:
            raise ValueError(f"Task item {index + 1} AI Validator Prompt text and file cannot both be set")
        requirements = workflow_requirements(project, workflow) if workflow_requirements else {}
        if workflow_requirements is not None and requirements.get("exists") is False:
            raise ValueError(f"Task item {index + 1} Workflow does not exist")
        if requirements.get("requires_python_validator") and not validator:
            raise ValueError(f"Task item {index + 1} File Validator is required by the selected Workflow")
        if not requirements.get("has_ai_validator") and (ai_validator_prompt or ai_validator_prompt_file):
            raise ValueError(f"Task item {index + 1} AI Validator Prompt requires an AI validation Workflow")
        item = {
            "title": bounded_text(raw.get("title"), f"Task item {index + 1} title", 240),
            "prompt": prompt,
            "goal_file": goal_file,
            "workflow": workflow,
            "project": project_path,
            "workspace": workspace,
            "validator": validator,
            "ai_validator_prompt": ai_validator_prompt,
            "ai_validator_prompt_file": ai_validator_prompt_file,
        }
        if item_id:
            item["item_id"] = item_id
        items.append(item)
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
