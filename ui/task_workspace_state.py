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

    def _write_task_marker(self, project: Path, task_id: str, request_id: str) -> None:
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
            # During the short launch gap read_runtime may not have the request
            # manifest yet. Once it does, a mismatched request must not attach to
            # the wrong Task.
            if request_id and marker_request and request_id != marker_request:
                runtime = None
                owns_visible_runtime = False

        if runtime is not None:
            status = str(runtime.get("status") or "idle")
            run_id = str(runtime.get("run_id") or "")
            execution_changes = {"last_status": status}
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
        # Persist terminal state of a prior Task before the canonical Runner
        # reset performed by launch_message().
        for existing in self.tasks.list(root=str(project)):
            self._sync_task(existing)

        task = self.tasks.create(
            chat_id=chat_id,
            root_path=str(project),
            instruction=instruction,
            title=title,
            task_type="single",
            workflow=workflow,
            source_message_id=source_message_id,
        )
        try:
            request = self.launch_message(project, instruction, workflow=workflow)
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
            "workflow": str(request.get("workflow") or ""),
            "run_id": "",
        })
        self._write_task_marker(project, task["task_id"], request_id)
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

        if action == "stop":
            if not owns_runtime or not actions.get("stop"):
                raise ValueError("Task cannot be stopped in its current state")
            self.stop(project)
        elif action == "resume":
            if not owns_runtime or not actions.get("resume"):
                raise ValueError("Task cannot be resumed in its current state")
            self.resume(project)
        elif action == "rerun":
            if not owns_runtime or not actions.get("rerun"):
                raise ValueError("Task cannot be rerun in its current state")
            request = self.rerun_last(
                project,
                workflow=str(task.get("workflow") or workflow or ""),
            )
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
            request = self.launch_message(
                project,
                text,
                workflow=workflow or str(task.get("workflow") or ""),
            )
            request_id = str(request.get("request_id") or "")
            task = self.tasks.append_execution(task_id, {
                "request_id": request_id,
                "started_at": time.time(),
                "instruction": text,
                "workflow": str(request.get("workflow") or ""),
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
