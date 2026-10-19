"""Durable Task records owned by the UI/Task service layer."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    from .task_models import validate_task_draft_for_create, validate_task_id
except ImportError:
    from task_models import validate_task_draft_for_create, validate_task_id

STATE_VERSION = 1
CREATE_REQUEST_LIMIT = 512
UPDATE_REQUEST_LIMIT = 512


class TaskService:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def list(self, project: Path) -> dict[str, Any]:
        with self._lock:
            state = self._load(project)
            return {"tasks": [deepcopy(row) for row in state["tasks"]]}

    def get(self, project: Path, task_id: str) -> dict[str, Any]:
        task_key = validate_task_id(task_id)
        with self._lock:
            state = self._load(project)
            for row in state["tasks"]:
                if row["task_id"] == task_key:
                    return deepcopy(row)
        raise ValueError("Task does not exist")

    def validate(self, project: Path, draft: Any) -> dict[str, Any]:
        """Validate transient editor data without creating durable Task state."""
        return {"draft": validate_task_draft_for_create(draft, project)}

    def create(self, project: Path, draft: Any, *, request_id: str) -> dict[str, Any]:
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        validated = validate_task_draft_for_create(draft, project)
        with self._lock:
            state = self._load(project)
            existing_id = state["create_requests"].get(request)
            if existing_id:
                for row in state["tasks"]:
                    if row["task_id"] == existing_id:
                        return {**deepcopy(row), "duplicate": True}
                raise ValueError("Task create request points to a missing Task")

            now = time.time()
            task_id = f"task-{uuid.uuid4().hex}"
            items = [
                {"item_id": f"{task_id}-item-{index + 1}", **item}
                for index, item in enumerate(validated["items"])
            ]
            task = {
                "schema_version": 1,
                "task_id": task_id,
                "kind": "task" if len(items) == 1 else "task_list",
                "title": validated["title"],
                "project": str(project.resolve()),
                "status": "new",
                "items": items,
                "run_count": 0,
                "merge_failure_count": 0,
                "created_at": now,
                "updated_at": now,
            }
            state["tasks"].append(task)
            state["create_requests"][request] = task_id
            while len(state["create_requests"]) > CREATE_REQUEST_LIMIT:
                state["create_requests"].pop(next(iter(state["create_requests"])))
            self._write(project, state)
            return {**deepcopy(task), "duplicate": False}

    def update(
        self,
        project: Path,
        task_id: str,
        draft: Any,
        *,
        request_id: str,
        expected_updated_at: float | None = None,
    ) -> dict[str, Any]:
        task_key = validate_task_id(task_id)
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        validated = validate_task_draft_for_create(draft, project)
        raw_items = draft.get("items") if isinstance(draft, dict) else []
        with self._lock:
            state = self._load(project)
            existing_request = state["update_requests"].get(request)
            if existing_request:
                if existing_request != task_key:
                    raise ValueError("request_id belongs to another Task")
                for row in state["tasks"]:
                    if row["task_id"] == task_key:
                        return {**deepcopy(row), "duplicate": True}
                raise ValueError("Task update request points to a missing Task")

            task = next((row for row in state["tasks"] if row["task_id"] == task_key), None)
            if task is None:
                raise ValueError("Task does not exist")
            if task.get("status") != "new":
                raise ValueError("Task must be New before editing")
            if expected_updated_at is not None:
                try:
                    expected = float(expected_updated_at)
                except (TypeError, ValueError) as exc:
                    raise ValueError("expected_updated_at is invalid") from exc
                if abs(float(task.get("updated_at") or 0) - expected) > 1e-6:
                    raise ValueError("Task changed since this editor was opened; reload before saving")

            existing_ids = {
                str(item.get("item_id") or ""): item
                for item in task.get("items", [])
                if isinstance(item, dict) and str(item.get("item_id") or "")
            }
            used: set[str] = set()
            next_index = 1
            prefix = f"{task_key}-item-"
            for item_id in existing_ids:
                if item_id.startswith(prefix):
                    try:
                        next_index = max(next_index, int(item_id[len(prefix):]) + 1)
                    except ValueError:
                        pass

            items: list[dict[str, Any]] = []
            for index, item in enumerate(validated["items"]):
                raw = raw_items[index] if isinstance(raw_items, list) and index < len(raw_items) and isinstance(raw_items[index], dict) else {}
                item_id = str(raw.get("item_id") or "")
                if item_id not in existing_ids or item_id in used:
                    while f"{prefix}{next_index}" in existing_ids or f"{prefix}{next_index}" in used:
                        next_index += 1
                    item_id = f"{prefix}{next_index}"
                    next_index += 1
                used.add(item_id)
                items.append({"item_id": item_id, **item})

            task["title"] = validated["title"]
            task["kind"] = "task" if len(items) == 1 else "task_list"
            task["items"] = items
            task["updated_at"] = time.time()
            state["update_requests"][request] = task_key
            while len(state["update_requests"]) > UPDATE_REQUEST_LIMIT:
                state["update_requests"].pop(next(iter(state["update_requests"])))
            self._write(project, state)
            return {**deepcopy(task), "duplicate": False}

    def _load(self, project: Path) -> dict[str, Any]:
        path = self._state_path(project)
        if not path.exists():
            return {
                "version": STATE_VERSION,
                "tasks": [],
                "create_requests": {},
                "update_requests": {},
            }
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Task store is invalid: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
            raise ValueError("Unsupported Task store version")
        tasks = raw.get("tasks")
        requests = raw.get("create_requests")
        update_requests = raw.get("update_requests", {})
        if not isinstance(tasks, list) or not isinstance(requests, dict) or not isinstance(update_requests, dict):
            raise ValueError("Task store is invalid")
        ids: set[str] = set()
        normalized: list[dict[str, Any]] = []
        for row in tasks:
            if not isinstance(row, dict):
                raise ValueError("Task store contains an invalid Task")
            task_id = validate_task_id(str(row.get("task_id") or ""))
            if task_id in ids:
                raise ValueError("Task store contains duplicate Task ids")
            ids.add(task_id)
            if row.get("status") not in {"new", "ongoing", "paused", "closed"}:
                raise ValueError("Task store contains an invalid lifecycle status")
            normalized.append(row)
        return {
            "version": STATE_VERSION,
            "tasks": normalized,
            "create_requests": {
                str(key): str(value)
                for key, value in requests.items()
                if str(key).strip() and str(value) in ids
            },
            "update_requests": {
                str(key): str(value)
                for key, value in update_requests.items()
                if str(key).strip() and str(value) in ids
            },
        }

    @staticmethod
    def _state_path(project: Path) -> Path:
        return project.resolve() / ".ai-task-runner" / "ui" / "tasks.json"

    def _write(self, project: Path, state: dict[str, Any]) -> None:
        path = self._state_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
