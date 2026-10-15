"""Task product/UI operations over the existing Runner runtime."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from project_registry import path_key

try:
    from .task_index import TaskIndex
except ImportError:
    from task_index import TaskIndex

TASK_MARKER = "active-task.json"
DEFAULT_TASK_WORKFLOW = "ralphy_ai_validate.yaml"
MAX_TASK_LIST_ITEMS = 200


class TaskWorkspaceMixin:
    tasks: TaskIndex

    def _chat_for_task(self, chat_id: str) -> dict:
        chat = next((row for row in self.chats.list() if row.get("chat_id") == chat_id), None)
        if chat is None:
            raise ValueError("Chat not found")
        return chat

    def _task_marker_path(self, project: Path) -> Path:
        return project / ".ai-task-runner" / "ui" / TASK_MARKER

    def _read_task_marker(self, project: Path) -> dict:
        return self._read_json(self._task_marker_path(project)) or {}

    def _write_task_marker(self, project: Path, task_id: str, request_id: str = "") -> None:
        path = self._task_marker_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "task_id": task_id,
            "request_id": request_id,
            "updated_at": time.time(),
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def _clear_task_marker(self, project: Path, task_id: str) -> None:
        path = self._task_marker_path(project)
        marker = self._read_json(path) or {}
        if marker.get("task_id") != task_id:
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _resolve_task_workflow(self, project: Path, workflow: str = "") -> str:
        requested = str(workflow or "").strip()
        if requested:
            candidate = Path(requested).expanduser().resolve()
            allowed = {path_key(path) for path in self._known_workflow_paths(project)}
            if path_key(candidate) not in allowed or not candidate.is_file():
                raise ValueError("Selected Workflow is outside the allowed Global / Project Workflow asset roots")
            return str(candidate)
        catalog = self.studio_files(project)
        for item in catalog.get("workflows", []):
            if str(item.get("name") or "") == DEFAULT_TASK_WORKFLOW:
                candidate = Path(str(item.get("path") or "")).expanduser().resolve()
                if candidate.is_file():
                    return str(candidate)
        raise ValueError(f"Default Workflow is unavailable: {DEFAULT_TASK_WORKFLOW}")

    @staticmethod
    def _same_path(left: str | Path, right: str | Path) -> bool:
        return path_key(left) == path_key(right)

    def _sync_task(self, task: dict) -> dict:
        project = Path(str(task.get("root_path") or ""))
        if not project.is_dir():
            if task.get("last_status") != "path_unavailable":
                task = self.tasks.update(task["task_id"], last_status="path_unavailable")
            return {**task, "path_available": False, "runtime": None}

        marker = self._read_task_marker(project)
        owns_visible_runtime = marker.get("task_id") == task.get("task_id")
        runtime = self.read_runtime(project) if owns_visible_runtime else None
        if runtime is not None:
            request_id = str(runtime.get("request_id") or "")
            marker_request = str(marker.get("request_id") or "")
            if request_id and marker_request and request_id != marker_request:
                runtime = None
                owns_visible_runtime = False

        if runtime is not None:
            status = str(runtime.get("status") or "idle")
            execution_changes = {"last_status": status}
            if task.get("task_type") != "sequential":
                run_id = str(runtime.get("run_id") or "")
                if run_id:
                    execution_changes["run_id"] = run_id
            try:
                task = self.tasks.update_latest_execution(task["task_id"], **execution_changes)
            except ValueError:
                task = self.tasks.update(task["task_id"], last_status=status)
            if runtime.get("last_error"):
                task = self.tasks.update(task["task_id"], last_error=str(runtime.get("last_error") or ""))

        return {
            **task,
            "path_available": True,
            "runtime": runtime,
            "owns_runtime": owns_visible_runtime,
        }

    def tasks_payload(self, chat_id: str = "") -> dict:
        if chat_id:
            self._chat_for_task(chat_id)
        rows = [self._sync_task(task) for task in self.tasks.list(chat_id=chat_id)]
        rows.sort(key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0), reverse=True)
        return {"tasks": rows}

    def task_detail(self, task_id: str) -> dict:
        task = self._sync_task(self.tasks.get(task_id))
        run_ids = {
            str(item.get("run_id") or "")
            for item in task.get("executions", [])
            if str(item.get("run_id") or "")
        }
        history: list[dict] = []
        project = Path(task["root_path"])
        if project.is_dir() and run_ids:
            history = [
                row for row in self.messages(project)
                if str(row.get("run_id") or "") in run_ids
            ]
        return {**task, "history": history}

    def _sync_prior_tasks(self, project: Path) -> None:
        for existing in self.tasks.list(root=str(project)):
            self._sync_task(existing)

    def create_task(
        self,
        *,
        chat_id: str,
        instruction: str,
        title: str = "",
        workflow: str = "",
        source_message_id: str = "",
    ) -> dict:
        chat = self._chat_for_task(chat_id)
        if not chat.get("path_available"):
            raise ValueError("Chat path unavailable")
        project = Path(chat["root_path"])
        resolved_workflow = self._resolve_task_workflow(project, workflow)
        self._sync_prior_tasks(project)

        task = self.tasks.create(
            chat_id=chat_id,
            root_path=str(project),
            instruction=instruction,
            title=title,
            task_type="single",
            workflow=resolved_workflow,
            source_message_id=source_message_id,
        )
        try:
            request = self.launch_message(project, instruction, workflow=resolved_workflow)
        except Exception as exc:
            task = self.tasks.update(
                task["task_id"],
                last_status="needs_attention",
                last_error=str(exc),
            )
            return self._sync_task(task)

        request_id = str(request.get("request_id") or "")
        task = self.tasks.append_execution(task["task_id"], {
            "request_id": request_id,
            "started_at": time.time(),
            "instruction": instruction,
            "workflow": str(request.get("workflow") or resolved_workflow),
            "run_id": "",
        })
        self._write_task_marker(project, task["task_id"], request_id)
        return self._sync_task(task)

    def _write_task_list(self, project: Path, task_id: str, items: list[dict], segment: int) -> Path:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("Task List requires PyYAML") from exc
        folder = project / ".ai-task-runner" / "ui" / "task-lists"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{task_id}-{segment:03d}.yaml"
        payload = [
            {
                "prompt": item["instruction"],
                "workflow_file": item["workflow"],
            }
            for item in items
        ]
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def create_task_list(
        self,
        *,
        chat_id: str,
        items: list,
        title: str = "",
    ) -> dict:
        chat = self._chat_for_task(chat_id)
        if not chat.get("path_available"):
            raise ValueError("Chat path unavailable")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_TASK_LIST_ITEMS:
            raise ValueError(f"Task List requires 1-{MAX_TASK_LIST_ITEMS} items")
        project = Path(chat["root_path"])
        normalized: list[dict] = []
        for index, raw in enumerate(items, 1):
            if not isinstance(raw, dict):
                raise ValueError(f"Task List item {index} is invalid")
            instruction = str(raw.get("instruction") or "").strip()
            if not instruction:
                raise ValueError(f"Task List item {index} instruction is required")
            if len(instruction) > 20000:
                raise ValueError(f"Task List item {index} instruction is too long")
            normalized.append({
                "instruction": instruction,
                "workflow": self._resolve_task_workflow(project, str(raw.get("workflow") or "")),
            })

        self._sync_prior_tasks(project)
        task = self.tasks.create(
            chat_id=chat_id,
            root_path=str(project),
            instruction=f"Task List · {len(normalized)} items",
            title=title or normalized[0]["instruction"][:80],
            task_type="sequential",
        )
        task = self.tasks.update(task["task_id"], items=normalized)
        script = self._write_task_list(project, task["task_id"], normalized, 1)
        try:
            self.launch_script_task(project, str(script))
        except Exception as exc:
            task = self.tasks.update(task["task_id"], last_status="needs_attention", last_error=str(exc))
            return self._sync_task(task)

        task = self.tasks.append_execution(task["task_id"], {
            "request_id": "",
            "script_file": str(script),
            "started_at": time.time(),
            "instruction": task["instruction"],
            "workflow": "",
            "run_id": "",
            "item_count": len(normalized),
        })
        self._write_task_marker(project, task["task_id"])
        return self._sync_task(task)

    def task_action(
        self,
        task_id: str,
        action: str,
        *,
        instruction: str = "",
        workflow: str = "",
    ) -> dict:
        task = self._sync_task(self.tasks.get(task_id))
        project = Path(task["root_path"])
        if not project.is_dir():
            raise ValueError("Task path unavailable")
        marker = self._read_task_marker(project)
        owns_runtime = marker.get("task_id") == task_id
        runtime = self.read_runtime(project) if owns_runtime else {}
        actions = runtime.get("actions") if isinstance(runtime.get("actions"), dict) else {}
        sequential = task.get("task_type") == "sequential"
        executions = list(task.get("executions") or [])
        latest = executions[-1] if executions else {}

        if action == "stop":
            if not owns_runtime or not actions.get("stop"):
                raise ValueError("Task cannot be stopped in its current state")
            self.stop(project)
        elif action == "resume":
            if not owns_runtime or not actions.get("resume"):
                raise ValueError("Task cannot be resumed in its current state")
            if sequential:
                self.launch_script_task(project, str(latest.get("script_file") or ""), resume=True)
            else:
                self.resume(project)
        elif action == "rerun":
            if not owns_runtime:
                raise ValueError("Task cannot be rerun because it does not own the current runtime")
            if sequential:
                if runtime.get("running") or not (actions.get("run") or actions.get("rerun")):
                    raise ValueError("Task List cannot be rerun in its current state")
                script = str(latest.get("script_file") or "")
                self.launch_script_task(project, script)
                task = self.tasks.append_execution(task_id, {
                    "request_id": "",
                    "script_file": script,
                    "started_at": time.time(),
                    "instruction": task.get("instruction") or "",
                    "workflow": "",
                    "run_id": "",
                    "item_count": len(task.get("items") or []),
                })
                self._write_task_marker(project, task_id)
            else:
                if not actions.get("rerun"):
                    raise ValueError("Task cannot be rerun in its current state")
                request = self.rerun_last(project, workflow=str(task.get("workflow") or workflow or ""))
                request_id = str((request or {}).get("request_id") or "")
                task = self.tasks.append_execution(task_id, {
                    "request_id": request_id,
                    "started_at": time.time(),
                    "instruction": task.get("instruction") or "",
                    "workflow": str((request or {}).get("workflow") or ""),
                    "run_id": "",
                })
                self._write_task_marker(project, task_id, request_id)
        elif action == "continue":
            if owns_runtime and runtime.get("running"):
                raise ValueError("Stop the active Task before Continue")
            text = str(instruction or "").strip()
            if not text:
                raise ValueError("Continue requires a new instruction")
            resolved_workflow = self._resolve_task_workflow(
                project,
                workflow or (str(task.get("workflow") or "") if not sequential else ""),
            )
            if sequential:
                segment = len(executions) + 1
                item = {"instruction": text, "workflow": resolved_workflow}
                script = self._write_task_list(project, task_id, [item], segment)
                self.launch_script_task(project, str(script))
                task = self.tasks.append_execution(task_id, {
                    "request_id": "",
                    "script_file": str(script),
                    "started_at": time.time(),
                    "instruction": text,
                    "workflow": resolved_workflow,
                    "run_id": "",
                    "item_count": 1,
                })
                self._write_task_marker(project, task_id)
            else:
                request = self.launch_message(project, text, workflow=resolved_workflow)
                request_id = str(request.get("request_id") or "")
                task = self.tasks.append_execution(task_id, {
                    "request_id": request_id,
                    "started_at": time.time(),
                    "instruction": text,
                    "workflow": str(request.get("workflow") or resolved_workflow),
                    "run_id": "",
                })
                self._write_task_marker(project, task_id, request_id)
        else:
            raise ValueError("Unknown Task action")
        return self.task_detail(task_id)

    def delete_task(self, task_id: str) -> dict:
        task = self._sync_task(self.tasks.get(task_id))
        project = Path(task["root_path"])
        if project.is_dir():
            marker = self._read_task_marker(project)
            if marker.get("task_id") == task_id and self.read_runtime(project).get("running"):
                raise ValueError("Stop the active Task before deleting it")
            self._clear_task_marker(project, task_id)
        self.tasks.delete(task_id)
        return {"ok": True}
