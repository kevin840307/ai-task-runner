"""UI-owned Chat identities. Runner state and Project registry stay authoritative."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from project_registry import path_key, project_file_lock


class ChatIndex:
    def __init__(self, file: Path):
        self.file = Path(file)

    def _read(self) -> list[dict]:
        if not self.file.exists():
            return []
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Chat index is unreadable; refusing to overwrite history") from exc
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise ValueError("Chat index has an invalid format")
        return data

    def list(self, root: str = "") -> list[dict]:
        key = path_key(root) if root else ""
        rows = self._read()
        return [
            {**row, "path_available": Path(row["root_path"]).is_dir()}
            for row in rows
            if not key or path_key(row["root_path"]) == key
        ]

    def update(self, chat_id: str, **changes) -> dict:
        chat_id = str(chat_id or "")
        allowed = {"session_id", "backend", "model", "title", "archived"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("Unsupported Chat metadata update")
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with project_file_lock(self.file):
            rows = self._read()
            for index, row in enumerate(rows):
                if row.get("chat_id") != chat_id:
                    continue
                value = {**row, **changes, "updated_at": time.time()}
                rows[index] = value
                temporary = self.file.with_name(self.file.name + "." + chat_id + ".tmp")
                try:
                    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
                    os.replace(temporary, self.file)
                finally:
                    temporary.unlink(missing_ok=True)
                return {**value, "path_available": Path(value["root_path"]).is_dir()}
        raise ValueError("Chat not found")

    def update(self, chat_id: str, **changes) -> dict:
        chat_id = str(chat_id or "")
        allowed = {"session_id", "backend", "model", "title"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("Unsupported Chat metadata update")
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with project_file_lock(self.file):
            rows = self._read()
            for index, row in enumerate(rows):
                if row.get("chat_id") != chat_id:
                    continue
                value = {**row, **changes, "updated_at": time.time()}
                rows[index] = value
                temporary = self.file.with_name(self.file.name + "." + chat_id + ".tmp")
                try:
                    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
                    os.replace(temporary, self.file)
                finally:
                    temporary.unlink(missing_ok=True)
                return {**value, "path_available": Path(value["root_path"]).is_dir()}
        raise ValueError("Chat not found")

    def create(self, root: str, title: str = "") -> dict:
        if not str(root).strip():
            raise ValueError("Chat root path is required")
        path = Path(root).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("Chat root folder does not exist")
        name = " ".join(title.split()) or path.name or "New Chat"
        if len(name) > 120:
            raise ValueError("Chat title is too long")
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with project_file_lock(self.file):
            rows = self._read()
            record = {
                "chat_id": uuid.uuid4().hex,
                "root_path": str(path),
                "title": name,
                "created_at": time.time(),
            }
            rows.append(record)
            temporary = self.file.with_name(self.file.name + "." + record["chat_id"] + ".tmp")
            try:
                temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temporary, self.file)
            finally:
                temporary.unlink(missing_ok=True)
        return {**record, "path_available": True}
