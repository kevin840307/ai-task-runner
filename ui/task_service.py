"""Durable Task records owned by the UI/Task service layer."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import yaml

try:
    from .task_models import validate_task_draft_for_create, validate_task_id
except ImportError:
    from task_models import validate_task_draft_for_create, validate_task_id

STATE_VERSION = 1
CREATE_REQUEST_LIMIT = 512
UPDATE_REQUEST_LIMIT = 512
DELETE_REQUEST_LIMIT = 512
RUN_REQUEST_LIMIT = 512
LIFECYCLE_REQUEST_LIMIT = 512
TASK_YAML_LIMIT = 256 * 1024
COMPLETED_ITEM_PHASES = frozenset({"merged", "no_changes", "worktree_ready"})
_EDITABLE_ITEM_FIELDS = (
    "title",
    "prompt",
    "goal_file",
    "workflow",
    "project",
    "workspace",
    "validator",
    "ai_validator_prompt",
    "ai_validator_prompt_file",
)


def _editable_item_value(item: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(item.get(key) or "")
        for key in _EDITABLE_ITEM_FIELDS
    }


def _safe_task_id(value: str) -> bool:
    try:
        validate_task_id(value)
        return True
    except ValueError:
        return False


class TaskService:
    def __init__(
        self,
        *,
        workflow_requirements: Callable[[Path, str], dict[str, Any]] | None = None,
        uploads: Any | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._workflow_requirements = workflow_requirements
        self._uploads = uploads

    @staticmethod
    def edit_policy(task: dict[str, Any]) -> dict[str, Any]:
        """Project the canonical Task/child edit policy without owning Runner state."""
        status = str(task.get("status") or "new")
        items = task.get("items") if isinstance(task.get("items"), list) else []
        try:
            completed = int(task.get("completed_item_count", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Task completed_item_count is invalid") from exc
        if completed < 0 or completed > len(items):
            raise ValueError("Task completed_item_count is out of range")

        if status == "new":
            editable = True
            reason = ""
        elif status == "paused":
            editable = True
            reason = ""
        elif status == "ongoing":
            editable = False
            reason = "Pause this Task before editing runtime-affecting content"
        else:
            editable = False
            reason = "Closed Tasks are read-only"

        current_index = completed if status == "paused" and completed < len(items) else None
        item_policies: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            item_id = str(item.get("item_id") or "") if isinstance(item, dict) else ""
            if not editable:
                state = "locked"
                can_edit = False
                can_restructure = False
                item_reason = reason
            elif status == "paused" and index < completed:
                state = "completed"
                can_edit = False
                can_restructure = False
                item_reason = "Completed Task items are locked"
            elif status == "paused" and index == current_index:
                state = "current"
                can_edit = True
                can_restructure = False
                item_reason = "Current paused item may be edited but not moved or removed"
            else:
                state = "future" if status == "paused" else "pending"
                can_edit = True
                can_restructure = True
                item_reason = ""
            item_policies.append({
                "item_id": item_id,
                "index": index,
                "state": state,
                "editable": can_edit,
                "restructure": can_restructure,
                "reason": item_reason,
            })
        retained_runtime = bool(task.get("run") or task.get("history"))
        cleanup = task.get("workspace_cleanup")
        cleanup_complete = (
            isinstance(cleanup, dict)
            and str(cleanup.get("status") or "") == "cleaned"
        )
        can_delete = (
            status in {"new", "closed"}
            and (not retained_runtime or cleanup_complete)
        )
        return {
            "editable": editable,
            "reason": reason,
            "completed_item_count": completed,
            "current_item_index": current_index,
            "can_rename": editable,
            "can_add_item": editable,
            "can_edit_yaml": status == "new" or (status == "paused" and completed == 0),
            "can_delete": can_delete,
            "can_cleanup": (
                status in {"new", "closed"}
                and retained_runtime
                and not cleanup_complete
            ),
            "restart_required": bool(task.get("restart_required", False)),
            "items": item_policies,
        }

    @classmethod
    def _project_task(cls, row: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(row)
        value["edit_policy"] = cls.edit_policy(row)
        return value

    def list(self, project: Path) -> dict[str, Any]:
        with self._lock:
            state = self._load(project)
            return {"tasks": [self._project_task(row) for row in state["tasks"]]}

    def get(self, project: Path, task_id: str) -> dict[str, Any]:
        task_key = validate_task_id(task_id)
        with self._lock:
            state = self._load(project)
            for row in state["tasks"]:
                if row["task_id"] == task_key:
                    return self._project_task(row)
        raise ValueError("Task does not exist")

    def validate(self, project: Path, draft: Any) -> dict[str, Any]:
        """Validate transient editor data without creating durable Task state."""
        return {"draft": validate_task_draft_for_create(draft, project, workflow_requirements=self._workflow_requirements)}

    def dump_yaml(self, project: Path, draft: Any) -> dict[str, Any]:
        """Serialize the canonical editable Task fields without runtime state."""
        validated = validate_task_draft_for_create(draft, project, workflow_requirements=self._workflow_requirements)
        raw_items = draft.get("items") if isinstance(draft, dict) else []
        items: list[dict[str, Any]] = []
        for index, item in enumerate(validated["items"]):
            raw = raw_items[index] if isinstance(raw_items, list) and index < len(raw_items) and isinstance(raw_items[index], dict) else {}
            row: dict[str, Any] = {}
            item_id = str(raw.get("item_id") or "").strip()
            if item_id:
                row["item_id"] = item_id
            row.update(item)
            items.append(row)
        payload = {
            "title": validated["title"],
            "items": items,
        }
        content = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        return {"content": content}

    def parse_yaml(self, project: Path, content: Any) -> dict[str, Any]:
        text = str(content or "")
        if not text.strip():
            raise ValueError("Task YAML is empty")
        if len(text.encode("utf-8")) > TASK_YAML_LIMIT:
            raise ValueError("Task YAML is too large")
        try:
            payload = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Task YAML is invalid: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Task YAML must contain an object")
        validated = validate_task_draft_for_create(payload, project, workflow_requirements=self._workflow_requirements)
        raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
        items: list[dict[str, Any]] = []
        for index, item in enumerate(validated["items"]):
            raw = raw_items[index] if index < len(raw_items) and isinstance(raw_items[index], dict) else {}
            item_id = str(raw.get("item_id") or "").strip()
            items.append(({"item_id": item_id} if item_id else {}) | item)
        return {
            "draft": {
                **validated,
                "items": items,
            }
        }

    def create(
        self,
        project: Path,
        draft: Any,
        *,
        request_id: str,
        project_id: str = "",
    ) -> dict[str, Any]:
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        validated = validate_task_draft_for_create(draft, project, workflow_requirements=self._workflow_requirements)
        with self._lock:
            state = self._load(project)
            existing_id = state["create_requests"].get(request)
            if existing_id:
                for row in state["tasks"]:
                    if row["task_id"] == existing_id:
                        return {**self._project_task(row), "duplicate": True}
                raise ValueError("Task create request points to a missing Task")

            now = time.time()
            task_id = f"task-{uuid.uuid4().hex}"
            items: list[dict[str, Any]] = []
            for index, item in enumerate(validated["items"]):
                item_id = str(item.get("item_id") or f"{task_id}-item-{index + 1}")
                payload = {key: value for key, value in item.items() if key != "item_id"}
                items.append({"item_id": item_id, **payload})
            task = {
                "schema_version": 1,
                "task_id": task_id,
                "kind": "task" if len(items) == 1 else "task_list",
                "title": validated["title"],
                "project_id": str(project_id or "").strip(),
                "project": str(project.resolve()),
                "status": "new",
                "items": items,
                "completed_item_count": 0,
                "restart_required": False,
                "run_count": 0,
                "merge_failure_count": 0,
                "created_at": now,
                "updated_at": now,
            }
            materialized = self._uploads.materialize_items(project, items) if self._uploads else []
            state["tasks"].append(task)
            state["create_requests"][request] = task_id
            while len(state["create_requests"]) > CREATE_REQUEST_LIMIT:
                state["create_requests"].pop(next(iter(state["create_requests"])))
            self._write(project, state)
            if self._uploads:
                self._uploads.finalize(project, materialized)
            return {**self._project_task(task), "duplicate": False}

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
        validated = validate_task_draft_for_create(draft, project, workflow_requirements=self._workflow_requirements)
        raw_items = draft.get("items") if isinstance(draft, dict) else []
        with self._lock:
            state = self._load(project)
            existing_request = state["update_requests"].get(request)
            if existing_request:
                if existing_request != task_key:
                    raise ValueError("request_id belongs to another Task")
                for row in state["tasks"]:
                    if row["task_id"] == task_key:
                        return {**self._project_task(row), "duplicate": True}
                raise ValueError("Task update request points to a missing Task")

            task = next((row for row in state["tasks"] if row["task_id"] == task_key), None)
            if task is None:
                raise ValueError("Task does not exist")
            status = str(task.get("status") or "")
            if status not in {"new", "paused"}:
                raise ValueError("Task must be New or Paused before editing")
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
                item_id = str(item.get("item_id") or raw.get("item_id") or "")
                if not item_id or item_id in used:
                    while f"{prefix}{next_index}" in existing_ids or f"{prefix}{next_index}" in used:
                        next_index += 1
                    item_id = f"{prefix}{next_index}"
                    next_index += 1
                used.add(item_id)
                payload = {key: value for key, value in item.items() if key != "item_id"}
                items.append({"item_id": item_id, **payload})

            restart_required = bool(task.get("restart_required", False))
            if status == "paused":
                policy = self.edit_policy(task)
                completed = int(policy["completed_item_count"])
                previous_items = task.get("items") if isinstance(task.get("items"), list) else []
                locked_prefix = previous_items[:completed]
                if len(items) < completed:
                    raise ValueError("Completed Task items cannot be removed while Paused")
                for index, previous in enumerate(locked_prefix):
                    current = items[index]
                    if str(current.get("item_id") or "") != str(previous.get("item_id") or ""):
                        raise ValueError("Completed Task items cannot be reordered while Paused")
                    if _editable_item_value(current) != _editable_item_value(previous):
                        raise ValueError("Completed Task items cannot be modified while Paused")
                current_index = policy.get("current_item_index")
                if isinstance(current_index, int):
                    previous = previous_items[current_index]
                    if len(items) <= current_index or str(items[current_index].get("item_id") or "") != str(previous.get("item_id") or ""):
                        raise ValueError("Current paused Task item cannot be moved or removed")
                    if _editable_item_value(items[current_index]) != _editable_item_value(previous):
                        restart_required = True

            materialized = self._uploads.materialize_items(project, items) if self._uploads else []
            task["title"] = validated["title"]
            task["kind"] = "task" if len(items) == 1 else "task_list"
            task["items"] = items
            task["completed_item_count"] = int(task.get("completed_item_count", 0))
            task["restart_required"] = restart_required
            task["updated_at"] = time.time()
            state["update_requests"][request] = task_key
            while len(state["update_requests"]) > UPDATE_REQUEST_LIMIT:
                state["update_requests"].pop(next(iter(state["update_requests"])))
            self._write(project, state)
            if self._uploads:
                self._uploads.finalize(project, materialized)
            return {**self._project_task(task), "duplicate": False}

    def delete(
        self,
        project: Path,
        task_id: str,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        task_key = validate_task_id(task_id)
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        with self._lock:
            state = self._load(project)
            existing = state["delete_requests"].get(request)
            if existing:
                if existing != task_key:
                    raise ValueError("request_id belongs to another Task")
                return {"task_id": task_key, "deleted": True, "duplicate": True}

            index = next((i for i, row in enumerate(state["tasks"]) if row["task_id"] == task_key), -1)
            if index < 0:
                raise ValueError("Task does not exist")
            task = state["tasks"][index]
            if not self.edit_policy(task)["can_delete"]:
                raise ValueError(
                    "Task runtime/workspaces must be explicitly cleaned up before deletion"
                )
            state["tasks"].pop(index)
            state["delete_requests"][request] = task_key
            while len(state["delete_requests"]) > DELETE_REQUEST_LIMIT:
                state["delete_requests"].pop(next(iter(state["delete_requests"])))
            self._write(project, state)
            return {"task_id": task_key, "deleted": True, "duplicate": False}

    def reset_to_new(
        self,
        project: Path,
        task_id: str,
        *,
        request_id: str,
        action: str,
    ) -> dict[str, Any]:
        """Archive the current lifecycle state and return a retained Task to New."""
        task_key = validate_task_id(task_id)
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        lifecycle_action = str(action or "").strip().lower()
        if lifecycle_action not in {"reset", "rerun"}:
            raise ValueError("Unsupported Task lifecycle action")

        with self._lock:
            state = self._load(project)
            existing = state["lifecycle_requests"].get(request)
            task = next((row for row in state["tasks"] if row["task_id"] == task_key), None)
            if task is None:
                raise ValueError("Task does not exist")
            if existing:
                if (
                    str(existing.get("task_id") or "") != task_key
                    or str(existing.get("action") or "") != lifecycle_action
                ):
                    raise ValueError("request_id belongs to another Task lifecycle action")
                return {**self._project_task(task), "duplicate": True}

            status = str(task.get("status") or "")
            if lifecycle_action == "reset" and status != "paused":
                raise ValueError("Task must be Paused before Reset")
            if lifecycle_action == "rerun" and status not in {"paused", "closed"}:
                raise ValueError("Task must be Paused or Closed before Rerun")

            now = time.time()
            current_run = task.get("run")
            if isinstance(current_run, dict):
                history = task.get("history")
                if not isinstance(history, list):
                    history = []
                archived = deepcopy(current_run)
                archived["lifecycle_end"] = lifecycle_action
                archived["archived_at"] = now
                archived["merge_failure_count"] = int(task.get("merge_failure_count", 0))
                history.append(archived)
                task["history"] = history[-100:]

            task.pop("run", None)
            task.pop("workspace_cleanup", None)
            task["status"] = "new"
            task["completed_item_count"] = 0
            task["restart_required"] = False
            task["merge_failure_count"] = 0
            task["updated_at"] = now
            state["lifecycle_requests"][request] = {
                "task_id": task_key,
                "action": lifecycle_action,
            }
            while len(state["lifecycle_requests"]) > LIFECYCLE_REQUEST_LIMIT:
                state["lifecycle_requests"].pop(next(iter(state["lifecycle_requests"])))
            self._write(project, state)
            return {**self._project_task(task), "duplicate": False}

    def record_workspace_cleanup(
        self,
        project: Path,
        task_id: str,
        *,
        request_id: str,
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Record completed explicit workspace cleanup without deleting Task history."""
        task_key = validate_task_id(task_id)
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
            raise ValueError("Workspace cleanup results must be a list of objects")
        with self._lock:
            state = self._load(project)
            existing = state["lifecycle_requests"].get(request)
            current = next((row for row in state["tasks"] if row["task_id"] == task_key), None)
            if current is None:
                raise ValueError("Task does not exist")
            if existing:
                if (
                    str(existing.get("task_id") or "") != task_key
                    or str(existing.get("action") or "") != "cleanup"
                ):
                    raise ValueError("request_id belongs to another Task lifecycle action")
                return {**self._project_task(current), "duplicate": True}
            if str(current.get("status") or "") not in {"new", "closed"}:
                raise ValueError("Task must be New or Closed before workspace cleanup")
            current["workspace_cleanup"] = {
                "status": "cleaned",
                "cleaned_at": time.time(),
                "results": deepcopy(results),
            }
            current["updated_at"] = time.time()
            state["lifecycle_requests"][request] = {
                "task_id": task_key,
                "action": "cleanup",
            }
            while len(state["lifecycle_requests"]) > LIFECYCLE_REQUEST_LIMIT:
                state["lifecycle_requests"].pop(next(iter(state["lifecycle_requests"])))
            self._write(project, state)
            return {**self._project_task(current), "duplicate": False}

    def lifecycle_request(self, project: Path, request_id: str) -> dict[str, Any] | None:
        """Return one durable Reset/Rerun request without mutating Task state."""
        request = str(request_id or "").strip()
        if not request:
            return None
        with self._lock:
            value = self._load(project)["lifecycle_requests"].get(request)
            return deepcopy(value) if isinstance(value, dict) else None

    def run_request(self, project: Path, request_id: str) -> dict[str, Any] | None:
        """Return the durable Task Run bound to one idempotency key, if any."""
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        with self._lock:
            state = self._load(project)
            existing = state["run_requests"].get(request)
            if existing is None:
                return None
            task_id = str(existing.get("task_id") or "")
            run_number = int(existing.get("run_number") or 0)
            task = next((row for row in state["tasks"] if row["task_id"] == task_id), None)
            if task is None:
                raise ValueError("Task Run request points to a missing Task")
            run = task.get("run")
            current_run = int(run.get("run_number") or 0) if isinstance(run, dict) else 0
            if current_run < run_number:
                raise ValueError("Task Run request points to stale Task state")
            return self._project_task(task)

    def begin_run(
        self,
        project: Path,
        task_id: str,
        *,
        request_id: str,
        workspace: dict[str, Any],
    ) -> dict[str, Any]:
        """Attach one durable Task Run identity before Runner launch."""
        task_key = validate_task_id(task_id)
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        if not isinstance(workspace, dict):
            raise ValueError("Workspace metadata must be an object")
        try:
            run_number = int(workspace.get("run_number"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Workspace run_number is invalid") from exc
        if str(workspace.get("task_id") or "") != task_key or run_number <= 0:
            raise ValueError("Workspace identity does not match Task")
        if not str(workspace.get("project_root") or "").strip():
            raise ValueError("Workspace project_root is required")

        with self._lock:
            state = self._load(project)
            existing = state["run_requests"].get(request)
            task = next((row for row in state["tasks"] if row["task_id"] == task_key), None)
            if task is None:
                raise ValueError("Task does not exist")
            if existing:
                if str(existing.get("task_id") or "") != task_key:
                    raise ValueError("request_id belongs to another Task")
                if int(existing.get("run_number") or 0) != run_number:
                    raise ValueError("request_id belongs to another Task Run")
                return {**self._project_task(task), "duplicate": True}

            status = str(task.get("status") or "")
            items = task.get("items") if isinstance(task.get("items"), list) else []
            completed = int(task.get("completed_item_count", 0))
            previous = task.get("run")
            sequence_ready = (
                status == "ongoing"
                and isinstance(previous, dict)
                and str(previous.get("phase") or "") in COMPLETED_ITEM_PHASES
                and completed == int(previous.get("item_index") or 0) + 1
            )
            if status not in {"new", "paused"} and not sequence_ready:
                raise ValueError("Task must be New, Paused, or between completed Task List items before starting")
            if completed >= len(items):
                raise ValueError("Task has no remaining item to run")
            expected_run = int(task.get("run_count", 0)) + 1
            if run_number != expected_run:
                raise ValueError("Workspace run_number does not match the next Task Run")

            if isinstance(previous, dict):
                history = task.get("history")
                if not isinstance(history, list):
                    history = []
                history.append(deepcopy(previous))
                task["history"] = history[-100:]

            now = time.time()
            task["status"] = "ongoing"
            task.pop("workspace_cleanup", None)
            task["run_count"] = run_number
            task["restart_required"] = False
            task["run"] = {
                "run_number": run_number,
                "item_index": completed,
                "phase": "launching",
                "workspace": deepcopy(workspace),
                "started_at": now,
                "updated_at": now,
                "error": "",
                "workspace_result": {},
            }
            task["updated_at"] = now
            state["run_requests"][request] = {
                "task_id": task_key,
                "run_number": run_number,
            }
            while len(state["run_requests"]) > RUN_REQUEST_LIMIT:
                state["run_requests"].pop(next(iter(state["run_requests"])))
            self._write(project, state)
            return {**self._project_task(task), "duplicate": False}

    def transition_run(
        self,
        project: Path,
        task_id: str,
        run_number: int,
        *,
        phase: str,
        status: str | None = None,
        error: str | None = None,
        workspace_result: dict[str, Any] | None = None,
        completed_item_count: int | None = None,
        increment_merge_failure: bool = False,
    ) -> dict[str, Any]:
        """Persist Task-orchestrator state only; Runner runtime remains projected."""
        task_key = validate_task_id(task_id)
        next_phase = str(phase or "").strip()
        if not next_phase:
            raise ValueError("Task Run phase is required")
        if status is not None and status not in {"new", "ongoing", "paused", "closed"}:
            raise ValueError("Invalid Task lifecycle status")
        try:
            expected_run = int(run_number)
        except (TypeError, ValueError) as exc:
            raise ValueError("Task Run number is invalid") from exc
        with self._lock:
            state = self._load(project)
            task = next((row for row in state["tasks"] if row["task_id"] == task_key), None)
            if task is None:
                raise ValueError("Task does not exist")
            run = task.get("run")
            if not isinstance(run, dict) or int(run.get("run_number") or 0) != expected_run:
                raise ValueError("Task Run identity is stale")
            now = time.time()
            run["phase"] = next_phase
            run["updated_at"] = now
            if error is not None:
                run["error"] = str(error)
            if workspace_result is not None:
                if not isinstance(workspace_result, dict):
                    raise ValueError("workspace_result must be an object")
                run["workspace_result"] = deepcopy(workspace_result)
            if completed_item_count is not None:
                try:
                    completed = int(completed_item_count)
                except (TypeError, ValueError) as exc:
                    raise ValueError("completed_item_count is invalid") from exc
                items = task.get("items") if isinstance(task.get("items"), list) else []
                if completed < 0 or completed > len(items):
                    raise ValueError("completed_item_count is out of range")
                task["completed_item_count"] = completed
            if increment_merge_failure:
                task["merge_failure_count"] = int(task.get("merge_failure_count", 0)) + 1
            if status is not None:
                task["status"] = status
            task["updated_at"] = now
            self._write(project, state)
            return self._project_task(task)

    def _load(self, project: Path) -> dict[str, Any]:
        path = self._state_path(project)
        if not path.exists():
            return {
                "version": STATE_VERSION,
                "tasks": [],
                "create_requests": {},
                "update_requests": {},
                "delete_requests": {},
                "run_requests": {},
                "lifecycle_requests": {},
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
        delete_requests = raw.get("delete_requests", {})
        run_requests = raw.get("run_requests", {})
        lifecycle_requests = raw.get("lifecycle_requests", {})
        if (
            not isinstance(tasks, list)
            or not isinstance(requests, dict)
            or not isinstance(update_requests, dict)
            or not isinstance(delete_requests, dict)
            or not isinstance(run_requests, dict)
            or not isinstance(lifecycle_requests, dict)
        ):
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
            items = row.get("items")
            if not isinstance(items, list) or not items:
                raise ValueError("Task store contains invalid Task items")
            try:
                completed = int(row.get("completed_item_count", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError("Task store contains invalid completed_item_count") from exc
            if completed < 0 or completed > len(items):
                raise ValueError("Task store contains invalid completed_item_count")
            restart_required = row.get("restart_required", False)
            if not isinstance(restart_required, bool):
                raise ValueError("Task store contains invalid restart_required")
            row = {
                **row,
                "completed_item_count": completed,
                "restart_required": restart_required,
            }
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
            "delete_requests": {
                str(key): str(value)
                for key, value in delete_requests.items()
                if str(key).strip() and _safe_task_id(str(value))
            },
            "run_requests": {
                str(key): {
                    "task_id": str(value.get("task_id") or ""),
                    "run_number": int(value.get("run_number") or 0),
                }
                for key, value in run_requests.items()
                if (
                    str(key).strip()
                    and isinstance(value, dict)
                    and str(value.get("task_id") or "") in ids
                    and str(value.get("run_number") or "").isdigit()
                    and int(value.get("run_number") or 0) > 0
                )
            },
            "lifecycle_requests": {
                str(key): {
                    "task_id": str(value.get("task_id") or ""),
                    "action": str(value.get("action") or ""),
                }
                for key, value in lifecycle_requests.items()
                if (
                    str(key).strip()
                    and isinstance(value, dict)
                    and str(value.get("task_id") or "") in ids
                    and str(value.get("action") or "") in {"reset", "rerun", "cleanup"}
                )
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
