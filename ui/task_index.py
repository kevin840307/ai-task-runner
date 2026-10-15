"""UI-owned durable Task index.

This stores product identity/references only. Runner state remains authoritative for
execution status, recovery, routing and allowed actions.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from project_registry import path_key, project_file_lock


class TaskIndex:
    def __init__(self, file: Path):
        self.file = Path(file)

    def _read(self) -> list[dict]:
        if not self.file.exists():
            return []
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Task index is unreadable; refusing to overwrite history") from exc
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise ValueError("Task index has an invalid format")
        seen: set[str] = set()
        for item in data:
            try:
                task_id = self._task_id(item.get("task_id"))
            except ValueError as exc:
                raise ValueError("Task index has an invalid task_id") from exc
            chat_id = item.get("chat_id")
            root_path = item.get("root_path")
            if not isinstance(chat_id, str) or not chat_id:
                raise ValueError("Task index has an invalid chat_id")
            if not isinstance(root_path, str) or not root_path.strip():
                raise ValueError("Task index has an invalid root_path")
            if task_id in seen:
                raise ValueError("Task index has duplicate task_id values")
            if "executions" in item and not isinstance(item.get("executions"), list):
                raise ValueError("Task index has invalid executions")
            seen.add(task_id)
        return data

    def _write(self, rows: list[dict]) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.file.with_name(self.file.name + ".tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.file)

    @staticmethod
    def _task_id(value: str) -> str:
        value = str(value or "")
        if len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("Invalid Task identity")
        return value

    def list(self, *, chat_id: str = "", root: str = "") -> list[dict]:
        root_key = path_key(root) if root else ""
        return [
            row
            for row in self._read()
            if (not chat_id or row.get("chat_id") == chat_id)
            and (not root_key or path_key(str(row.get("root_path") or "")) == root_key)
        ]

    def get(self, task_id: str) -> dict:
        task_id = self._task_id(task_id)
        task = next((row for row in self._read() if row.get("task_id") == task_id), None)
        if task is None:
            raise ValueError("Task not found")
        return task

    def create(
        self,
        *,
        chat_id: str,
        root_path: str,
        instruction: str,
        title: str = "",
        task_type: str = "single",
        workflow: str = "",
        source_message_id: str = "",
    ) -> dict:
        instruction = str(instruction or "").strip()
        if not instruction:
            raise ValueError("Task instruction is required")
        if len(instruction) > 20000:
            raise ValueError("Task instruction is too long")
        task_type = str(task_type or "single")
        if task_type not in {"single", "sequential"}:
            raise ValueError("Task type must be single or sequential")
        label = " ".join(str(title or "").split()) or instruction.splitlines()[0][:80]
        if len(label) > 120:
            raise ValueError("Task title is too long")
        now = time.time()
        record = {
            "task_id": uuid.uuid4().hex,
            "chat_id": str(chat_id),
            "root_path": str(Path(root_path).expanduser().resolve()),
            "title": label,
            "task_type": task_type,
            "instruction": instruction,
            "workflow": str(workflow or ""),
            "source_message_id": str(source_message_id or ""),
            "created_at": now,
            "updated_at": now,
            "executions": [],
            "last_status": "pending",
            "last_error": "",
        }
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with project_file_lock(self.file):
            rows = self._read()
            rows.append(record)
            self._write(rows)
        return record

    def update(self, task_id: str, **changes) -> dict:
        task_id = self._task_id(task_id)
        with project_file_lock(self.file):
            rows = self._read()
            for index, row in enumerate(rows):
                if row.get("task_id") != task_id:
                    continue
                updated = {**row, **changes, "updated_at": time.time()}
                rows[index] = updated
                self._write(rows)
                return updated
        raise ValueError("Task not found")

    def append_execution(self, task_id: str, execution: dict) -> dict:
        task = self.get(task_id)
        executions = list(task.get("executions") or [])
        executions.append(dict(execution))
        return self.update(task_id, executions=executions, last_error="", last_status="launching")

    def update_latest_execution(self, task_id: str, **changes) -> dict:
        task = self.get(task_id)
        executions = list(task.get("executions") or [])
        if not executions:
            raise ValueError("Task has no execution")
        executions[-1] = {**executions[-1], **changes}
        return self.update(task_id, executions=executions, **{
            key: value for key, value in changes.items() if key in {"last_status", "last_error"}
        })

    def delete(self, task_id: str) -> None:
        task_id = self._task_id(task_id)
        with project_file_lock(self.file):
            rows = self._read()
            kept = [row for row in rows if row.get("task_id") != task_id]
            if len(kept) == len(rows):
                raise ValueError("Task not found")
            self._write(kept)
