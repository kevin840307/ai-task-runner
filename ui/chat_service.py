"""Durable Project Chat session/message storage owned by the UI backend.

Project Chat is deliberately separate from Runner task history.  This module
owns only chat identity and persisted conversation records; it does not launch
or inspect Runner workflows.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

CHAT_DIR = ".ai-task-runner/ui/chat"
STATE_FILE = "state.json"
STATE_VERSION = 1
MESSAGE_READ_LIMIT = 500
CREATE_REQUEST_LIMIT = 256
_SESSION_ID = re.compile(r"^chat-[0-9a-f]{32}$")
_MESSAGE_ID = re.compile(r"^msg-[0-9a-f]{32}$")


class ChatService:
    """Single owner for Project Chat session identity and message history."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def sessions(self, project: Path) -> dict[str, Any]:
        with self._lock:
            state = self._load(project)
            changed = self._ensure_session(state)
            if changed:
                self._write(project, state)
            return self._snapshot(state)

    def create_session(
        self,
        project: Path,
        *,
        title: str = "",
        request_id: str = "",
    ) -> dict[str, Any]:
        request = self._request_id(request_id)
        with self._lock:
            state = self._load(project)
            existing = str(state["create_requests"].get(request) or "")
            if existing:
                self._require_session(state, existing)
                state["active_session_id"] = existing
                return self._snapshot(state, session_id=existing)

            session = self._new_session(title)
            state["sessions"].append(session)
            state["active_session_id"] = session["session_id"]
            state["create_requests"][request] = session["session_id"]
            self._trim_create_requests(state)
            self._write(project, state)
            return self._snapshot(state, session_id=session["session_id"])

    def select_session(self, project: Path, session_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            state["active_session_id"] = session["session_id"]
            self._write(project, state)
            return self._snapshot(state, session_id=session["session_id"])

    def rename_session(self, project: Path, session_id: str, title: str) -> dict[str, Any]:
        label = self._title(title, required=True)
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            session["title"] = label
            session["updated_at"] = time.time()
            self._write(project, state)
            return self._snapshot(state, session_id=session["session_id"])

    def delete_session(self, project: Path, session_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            state["sessions"] = [
                row for row in state["sessions"]
                if row["session_id"] != session["session_id"]
            ]
            for request, created_id in list(state["create_requests"].items()):
                if created_id == session["session_id"]:
                    del state["create_requests"][request]
            message_file = self._messages_path(project, session["session_id"])
            try:
                message_file.unlink()
            except FileNotFoundError:
                pass

            if not state["sessions"]:
                replacement = self._new_session("")
                state["sessions"].append(replacement)
            if state["active_session_id"] == session["session_id"]:
                state["active_session_id"] = state["sessions"][0]["session_id"]
            self._write(project, state)
            return self._snapshot(state)

    def messages(self, project: Path, session_id: str = "") -> dict[str, Any]:
        with self._lock:
            state = self._load(project)
            if self._ensure_session(state):
                self._write(project, state)
            resolved = session_id or state["active_session_id"]
            session = self._require_session(state, resolved)
            rows: list[dict[str, Any]] = []
            path = self._messages_path(project, session["session_id"])
            if path.is_file():
                try:
                    for line in path.read_text(encoding="utf-8").splitlines():
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if (
                            isinstance(row, dict)
                            and _MESSAGE_ID.fullmatch(str(row.get("message_id") or ""))
                            and row.get("role") in {"user", "assistant", "system"}
                        ):
                            rows.append(row)
                except OSError as exc:
                    raise ValueError(f"Chat messages unavailable: {exc}") from exc
            return {
                "session_id": session["session_id"],
                "messages": rows[-MESSAGE_READ_LIMIT:],
            }

    def append_message(
        self,
        project: Path,
        session_id: str,
        role: str,
        content: str,
    ) -> dict[str, Any]:
        text = str(content or "")
        if not text.strip():
            raise ValueError("Chat message is empty")
        if role not in {"user", "assistant", "system"}:
            raise ValueError("Invalid Chat message role")
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            row = {
                "message_id": f"msg-{uuid.uuid4().hex}",
                "role": role,
                "content": text,
                "time": time.time(),
            }
            path = self._messages_path(project, session["session_id"])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            session["updated_at"] = row["time"]
            self._write(project, state)
            return dict(row)

    def _load(self, project: Path) -> dict[str, Any]:
        path = self._state_path(project)
        if not path.exists():
            return self._empty_state()
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Chat state is invalid: {exc}") from exc
        if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
            raise ValueError("Unsupported Chat state version")
        sessions = state.get("sessions")
        create_requests = state.get("create_requests")
        if not isinstance(sessions, list) or not isinstance(create_requests, dict):
            raise ValueError("Chat state is invalid")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in sessions:
            if not isinstance(row, dict):
                raise ValueError("Chat state is invalid")
            session_id = str(row.get("session_id") or "")
            if not _SESSION_ID.fullmatch(session_id) or session_id in seen:
                raise ValueError("Chat state contains an invalid session")
            seen.add(session_id)
            normalized.append({
                "session_id": session_id,
                "title": self._title(str(row.get("title") or "")),
                "created_at": float(row.get("created_at") or 0),
                "updated_at": float(row.get("updated_at") or 0),
            })
        active = str(state.get("active_session_id") or "")
        if active and active not in seen:
            raise ValueError("Chat state active session is invalid")
        return {
            "version": STATE_VERSION,
            "active_session_id": active,
            "sessions": normalized,
            "create_requests": {
                str(key): str(value)
                for key, value in create_requests.items()
                if str(key).strip() and str(value) in seen
            },
        }

    def _write(self, project: Path, state: dict[str, Any]) -> None:
        path = self._state_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "active_session_id": "",
            "sessions": [],
            "create_requests": {},
        }

    def _ensure_session(self, state: dict[str, Any]) -> bool:
        if state["sessions"]:
            if not state["active_session_id"]:
                state["active_session_id"] = state["sessions"][0]["session_id"]
                return True
            return False
        session = self._new_session("")
        state["sessions"].append(session)
        state["active_session_id"] = session["session_id"]
        return True

    def _new_session(self, title: str) -> dict[str, Any]:
        now = time.time()
        return {
            "session_id": f"chat-{uuid.uuid4().hex}",
            "title": self._title(title),
            "created_at": now,
            "updated_at": now,
        }

    @staticmethod
    def _title(value: str, *, required: bool = False) -> str:
        label = " ".join(str(value or "").split())
        if required and not label:
            raise ValueError("Chat title is required")
        if len(label) > 80:
            raise ValueError("Chat title is too long")
        return label or "New Chat"

    @staticmethod
    def _request_id(value: str) -> str:
        request = str(value or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 160:
            raise ValueError("request_id is too long")
        return request

    @staticmethod
    def _trim_create_requests(state: dict[str, Any]) -> None:
        requests = state["create_requests"]
        while len(requests) > CREATE_REQUEST_LIMIT:
            requests.pop(next(iter(requests)))

    @staticmethod
    def _require_session(state: dict[str, Any], session_id: str) -> dict[str, Any]:
        value = str(session_id or "")
        if not _SESSION_ID.fullmatch(value):
            raise ValueError("Invalid Chat session_id")
        for row in state["sessions"]:
            if row["session_id"] == value:
                return row
        raise ValueError("Chat session does not exist")

    @staticmethod
    def _state_path(project: Path) -> Path:
        return project / CHAT_DIR / STATE_FILE

    @staticmethod
    def _messages_path(project: Path, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(str(session_id or "")):
            raise ValueError("Invalid Chat session_id")
        return project / CHAT_DIR / "sessions" / f"{session_id}.jsonl"

    @staticmethod
    def _snapshot(state: dict[str, Any], *, session_id: str = "") -> dict[str, Any]:
        return {
            "active_session_id": state["active_session_id"],
            "session_id": session_id or state["active_session_id"],
            "sessions": [dict(row) for row in state["sessions"]],
        }
