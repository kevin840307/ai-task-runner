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

try:
    from .chat_ask import normalize_questions, validate_answers
except ImportError:  # pragma: no cover - script import compatibility
    from chat_ask import normalize_questions, validate_answers

CHAT_DIR = ".ai-task-runner/ui/chat"
STATE_FILE = "state.json"
STATE_VERSION = 6
MESSAGE_READ_LIMIT = 500
CREATE_REQUEST_LIMIT = 256
TURN_REQUEST_LIMIT = 512
QUEUE_LIMIT = 100
_SESSION_ID = re.compile(r"^chat-[0-9a-f]{32}$")
_MESSAGE_ID = re.compile(r"^msg-[0-9a-f]{32}$")
_QUEUE_ID = re.compile(r"^queue-[0-9a-f]{32}$")
_ASK_ID = re.compile(r"^ask-[0-9a-f]{32}$")


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
                if state["active_session_id"] != existing:
                    state["active_session_id"] = existing
                    self._write(project, state)
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
            for request, row in list(state["turn_requests"].items()):
                if row["session_id"] == session["session_id"]:
                    del state["turn_requests"][request]
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

    def ask(self, project: Path, session_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            return {
                "session_id": session["session_id"],
                "ask": self._public_ask(session.get("ask")),
            }

    def create_ask(
        self,
        project: Path,
        session_id: str,
        *,
        request_id: str,
        questions: Any,
        turn_id: str = "",
        source: str = "local",
        backend: str = "",
        agent_session_id: str = "",
        native_request_id: str = "",
    ) -> dict[str, Any]:
        request = self._request_id(request_id)
        normalized_questions = normalize_questions(questions)
        turn = str(turn_id or "").strip() or f"turn-{uuid.uuid4().hex}"
        if len(turn) > 160:
            raise ValueError("Ask turn_id is too long")
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            existing = session.get("ask")
            if isinstance(existing, dict) and existing.get("status") == "waiting":
                if existing.get("request_id") == request:
                    return {
                        "session_id": session["session_id"],
                        "ask": self._public_ask(existing),
                        "duplicate": True,
                    }
                raise ValueError("Chat already has a pending Ask")
            now = time.time()
            value = {
                "ask_id": f"ask-{uuid.uuid4().hex}",
                "request_id": request,
                "turn_id": turn,
                "status": "waiting",
                "questions": normalized_questions,
                "answers": None,
                "answer_request_id": "",
                "resolution_kind": "",
                "source": str(source or "local").strip() or "local",
                "backend": str(backend or "").strip(),
                "agent_session_id": str(agent_session_id or "").strip(),
                "native_request_id": str(native_request_id or "").strip(),
                "created_at": now,
                "resolved_at": 0.0,
            }
            session["ask"] = value
            session["updated_at"] = now
            self._write(project, state)
            return {
                "session_id": session["session_id"],
                "ask": self._public_ask(value),
                "duplicate": False,
            }

    def begin_ask_resolution(
        self,
        project: Path,
        session_id: str,
        ask_id: str,
        answers: Any,
        *,
        request_id: str,
        cancelled: bool = False,
    ) -> dict[str, Any]:
        request = self._request_id(request_id)
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            ask = self._require_ask(session, ask_id)
            terminal = "cancelled" if cancelled else "answered"
            if ask["status"] == terminal and ask.get("answer_request_id") == request:
                return {
                    "session_id": session["session_id"],
                    "ask": self._public_ask(ask),
                    "duplicate": True,
                    "in_flight": False,
                }
            if ask["status"] == "resolving":
                if ask.get("answer_request_id") == request:
                    return {
                        "session_id": session["session_id"],
                        "ask": self._public_ask(ask),
                        "duplicate": True,
                        "in_flight": True,
                    }
                raise ValueError("Ask resolution is already in progress")
            if ask["status"] != "waiting":
                raise ValueError("Ask is no longer waiting for a response")
            ask["answers"] = None if cancelled else validate_answers(
                ask["questions"], answers
            )
            ask["answer_request_id"] = request
            ask["resolution_kind"] = "cancel" if cancelled else "answer"
            ask["status"] = "resolving"
            session["updated_at"] = time.time()
            self._write(project, state)
            return {
                "session_id": session["session_id"],
                "ask": self._public_ask(ask),
                "duplicate": False,
                "in_flight": True,
            }

    def finish_ask_resolution(
        self,
        project: Path,
        session_id: str,
        ask_id: str,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        request = self._request_id(request_id)
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            ask = self._require_ask(session, ask_id)
            if ask["status"] in {"answered", "cancelled"}:
                if ask.get("answer_request_id") == request:
                    return {
                        "session_id": session["session_id"],
                        "ask": self._public_ask(ask),
                        "duplicate": True,
                    }
                raise ValueError("Ask has already been resolved")
            if ask["status"] != "resolving" or ask.get("answer_request_id") != request:
                raise ValueError("Ask resolution request does not match")
            ask["status"] = (
                "cancelled"
                if ask.get("resolution_kind") == "cancel"
                else "answered"
            )
            ask["resolved_at"] = time.time()
            session["updated_at"] = ask["resolved_at"]
            self._write(project, state)
            return {
                "session_id": session["session_id"],
                "ask": self._public_ask(ask),
                "duplicate": False,
            }

    def abort_ask_resolution(
        self,
        project: Path,
        session_id: str,
        ask_id: str,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        request = self._request_id(request_id)
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            ask = self._require_ask(session, ask_id)
            if ask["status"] == "resolving" and ask.get("answer_request_id") == request:
                ask["status"] = "waiting"
                ask["answers"] = None
                ask["answer_request_id"] = ""
                ask["resolution_kind"] = ""
                session["updated_at"] = time.time()
                self._write(project, state)
            return {
                "session_id": session["session_id"],
                "ask": self._public_ask(ask),
            }

    def ask_context(
        self,
        project: Path,
        session_id: str,
        ask_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            ask = self._require_ask(session, ask_id)
            return {
                "ask_id": ask["ask_id"],
                "source": ask.get("source", "local"),
                "backend": ask.get("backend", ""),
                "agent_session_id": ask.get("agent_session_id", ""),
                "native_request_id": ask.get("native_request_id", ""),
                "turn_id": ask["turn_id"],
                "status": ask["status"],
                "answers": ask.get("answers"),
            }

    def submit_ask(
        self,
        project: Path,
        session_id: str,
        ask_id: str,
        answers: Any,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        started = self.begin_ask_resolution(
            project,
            session_id,
            ask_id,
            answers,
            request_id=request_id,
        )
        if started["duplicate"] and not started["in_flight"]:
            return started
        return self.finish_ask_resolution(
            project,
            session_id,
            ask_id,
            request_id=request_id,
        )

    def cancel_ask(
        self,
        project: Path,
        session_id: str,
        ask_id: str,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        started = self.begin_ask_resolution(
            project,
            session_id,
            ask_id,
            None,
            request_id=request_id,
            cancelled=True,
        )
        if started["duplicate"] and not started["in_flight"]:
            return started
        return self.finish_ask_resolution(
            project,
            session_id,
            ask_id,
            request_id=request_id,
        )

    def queue(self, project: Path, session_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            return self._queue_snapshot(session)

    def enqueue_turn(
        self,
        project: Path,
        session_id: str,
        content: str,
        *,
        request_id: str,
        backend: str,
        model: str = "",
        mode: str = "auto",
        reasoning: str = "",
    ) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            raise ValueError("Chat message is empty")
        request = self._request_id(request_id)
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            existing = state["turn_requests"].get(request)
            if existing is not None:
                if existing["session_id"] != session["session_id"]:
                    raise ValueError("request_id belongs to another Chat session")
                snapshot = self._queue_snapshot(session)
                return {
                    **snapshot,
                    "duplicate": True,
                    "queue_id": existing["queue_id"],
                    "request_status": existing["status"],
                }
            if len(session["queue"]) >= QUEUE_LIMIT:
                raise ValueError("Chat Queue is full")
            item = {
                "queue_id": f"queue-{uuid.uuid4().hex}",
                "request_id": request,
                "content": text,
                "created_at": time.time(),
                "status": "queued",
                "backend": str(backend or "").strip(),
                "model": str(model or "").strip(),
                "mode": str(mode or "auto").strip(),
                "reasoning": str(reasoning or "").strip(),
            }
            session["queue"].append(item)
            session["updated_at"] = item["created_at"]
            state["turn_requests"][request] = {
                "session_id": session["session_id"],
                "queue_id": item["queue_id"],
                "status": "queued",
            }
            self._trim_turn_requests(state)
            self._write(project, state)
            return {
                **self._queue_snapshot(session),
                "duplicate": False,
                "queue_id": item["queue_id"],
                "request_status": "queued",
            }

    def recover_dispatching(self, project: Path, session_id: str) -> None:
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            changed = False
            for item in session["queue"]:
                if item["status"] != "dispatching":
                    continue
                item["status"] = "queued"
                request = state["turn_requests"].get(item["request_id"])
                if request is not None:
                    request["status"] = "queued"
                changed = True
            if changed:
                self._write(project, state)

    def claim_next(self, project: Path, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            for item in session["queue"]:
                if item["status"] != "queued":
                    continue
                item["status"] = "dispatching"
                request = state["turn_requests"].get(item["request_id"])
                if request is not None:
                    request["status"] = "dispatching"
                self._write(project, state)
                return dict(item)
            return None

    def complete_queue_item(
        self,
        project: Path,
        session_id: str,
        queue_id: str,
        *,
        outcome: str = "completed",
    ) -> None:
        if outcome not in {"completed", "failed", "cancelled"}:
            raise ValueError("Invalid Chat Queue outcome")
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            item = self._require_queue_item(session, queue_id)
            session["queue"] = [
                row for row in session["queue"] if row["queue_id"] != item["queue_id"]
            ]
            request = state["turn_requests"].get(item["request_id"])
            if request is not None:
                request["status"] = outcome
            session["updated_at"] = time.time()
            self._trim_turn_requests(state)
            self._write(project, state)

    def update_queue_item(
        self,
        project: Path,
        session_id: str,
        queue_id: str,
        content: str,
    ) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            raise ValueError("Queued message is empty")
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            item = self._require_queue_item(session, queue_id)
            if item["status"] != "queued":
                raise ValueError("Only pending Queue items can be edited")
            item["content"] = text
            session["updated_at"] = time.time()
            self._write(project, state)
            return self._queue_snapshot(session)

    def delete_queue_item(
        self,
        project: Path,
        session_id: str,
        queue_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            item = self._require_queue_item(session, queue_id)
            if item["status"] != "queued":
                raise ValueError("Only pending Queue items can be deleted")
            session["queue"] = [
                row for row in session["queue"] if row["queue_id"] != item["queue_id"]
            ]
            request = state["turn_requests"].get(item["request_id"])
            if request is not None:
                request["status"] = "cancelled"
            session["updated_at"] = time.time()
            self._trim_turn_requests(state)
            self._write(project, state)
            return self._queue_snapshot(session)

    def _load(self, project: Path) -> dict[str, Any]:
        path = self._state_path(project)
        if not path.exists():
            return self._empty_state()
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Chat state is invalid: {exc}") from exc
        if not isinstance(state, dict) or state.get("version") not in {1, 2, 3, 4, 5, STATE_VERSION}:
            raise ValueError("Unsupported Chat state version")
        source_version = int(state.get("version"))
        legacy_v1 = source_version == 1
        legacy_before_reasoning = source_version in {1, 2}
        legacy_before_ask = source_version in {1, 2, 3}
        legacy_queue_status = source_version <= 4
        sessions = state.get("sessions")
        create_requests = state.get("create_requests")
        turn_requests = {} if legacy_v1 else state.get("turn_requests", {})
        if (
            not isinstance(sessions, list)
            or not isinstance(create_requests, dict)
            or not isinstance(turn_requests, dict)
        ):
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
            raw_queue = [] if legacy_v1 else row.get("queue", [])
            if not isinstance(raw_queue, list):
                raise ValueError("Chat state contains an invalid Queue")
            queue_rows: list[dict[str, Any]] = []
            queue_seen: set[str] = set()
            for item in raw_queue:
                if not isinstance(item, dict):
                    raise ValueError("Chat state contains an invalid Queue item")
                queue_id = str(item.get("queue_id") or "")
                request_id = str(item.get("request_id") or "")
                content = str(item.get("content") or "")
                status = str(item.get("status") or "")
                if legacy_queue_status and status == "processing":
                    status = "dispatching"
                if (
                    not _QUEUE_ID.fullmatch(queue_id)
                    or queue_id in queue_seen
                    or not request_id.strip()
                    or not content.strip()
                    or status not in {"queued", "dispatching"}
                ):
                    raise ValueError("Chat state contains an invalid Queue item")
                queue_seen.add(queue_id)
                queue_rows.append({
                    "queue_id": queue_id,
                    "request_id": request_id,
                    "content": content,
                    "created_at": float(item.get("created_at") or 0),
                    "status": status,
                    "backend": str(item.get("backend") or ""),
                    "model": str(item.get("model") or ""),
                    "mode": str(item.get("mode") or "auto"),
                    "reasoning": "" if legacy_before_reasoning else str(item.get("reasoning") or ""),
                })
            ask = None if legacy_before_ask else self._normalize_ask(row.get("ask"))
            normalized.append({
                "session_id": session_id,
                "title": self._title(str(row.get("title") or "")),
                "created_at": float(row.get("created_at") or 0),
                "updated_at": float(row.get("updated_at") or 0),
                "agent_backend": str(row.get("agent_backend") or ""),
                "agent_session_id": str(row.get("agent_session_id") or ""),
                "queue": queue_rows,
                "ask": ask,
            })
        active = str(state.get("active_session_id") or "")
        if active and active not in seen:
            raise ValueError("Chat state active session is invalid")
        normalized_turn_requests: dict[str, dict[str, str]] = {}
        for request_id, value in turn_requests.items():
            if not isinstance(value, dict):
                continue
            session_id = str(value.get("session_id") or "")
            queue_id = str(value.get("queue_id") or "")
            status = str(value.get("status") or "")
            if legacy_queue_status:
                status = {"processing": "dispatching", "done": "completed"}.get(status, status)
            if (
                str(request_id).strip()
                and session_id in seen
                and _QUEUE_ID.fullmatch(queue_id)
                and status in {"queued", "dispatching", "completed", "failed", "cancelled"}
            ):
                normalized_turn_requests[str(request_id)] = {
                    "session_id": session_id,
                    "queue_id": queue_id,
                    "status": status,
                }
        for session in normalized:
            for item in session["queue"]:
                normalized_turn_requests.setdefault(item["request_id"], {
                    "session_id": session["session_id"],
                    "queue_id": item["queue_id"],
                    "status": item["status"],
                })
        return {
            "version": STATE_VERSION,
            "active_session_id": active,
            "sessions": normalized,
            "create_requests": {
                str(key): str(value)
                for key, value in create_requests.items()
                if str(key).strip() and str(value) in seen
            },
            "turn_requests": normalized_turn_requests,
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
            "turn_requests": {},
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
            "agent_backend": "",
            "agent_session_id": "",
            "queue": [],
            "ask": None,
        }

    @staticmethod
    def _normalize_ask(raw: Any) -> dict[str, Any] | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValueError("Chat state contains an invalid Ask")
        ask_id = str(raw.get("ask_id") or "")
        request_id = str(raw.get("request_id") or "").strip()
        turn_id = str(raw.get("turn_id") or "").strip()
        status = str(raw.get("status") or "")
        if (
            not _ASK_ID.fullmatch(ask_id)
            or not request_id
            or not turn_id
            or status not in {"waiting", "resolving", "answered", "cancelled"}
        ):
            raise ValueError("Chat state contains an invalid Ask")
        questions = normalize_questions(raw.get("questions"))
        answers = None
        resolution_kind = str(raw.get("resolution_kind") or "")
        if status == "answered" or (
            status == "resolving" and resolution_kind == "answer"
        ):
            answers = validate_answers(questions, raw.get("answers"))
        return {
            "ask_id": ask_id,
            "request_id": request_id,
            "turn_id": turn_id,
            "status": status,
            "questions": questions,
            "answers": answers,
            "answer_request_id": str(raw.get("answer_request_id") or ""),
            "resolution_kind": resolution_kind,
            "source": str(raw.get("source") or "local"),
            "backend": str(raw.get("backend") or ""),
            "agent_session_id": str(raw.get("agent_session_id") or ""),
            "native_request_id": str(raw.get("native_request_id") or ""),
            "created_at": float(raw.get("created_at") or 0),
            "resolved_at": float(raw.get("resolved_at") or 0),
        }

    @staticmethod
    def _public_ask(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        return {
            "ask_id": raw["ask_id"],
            "request_id": raw["request_id"],
            "turn_id": raw["turn_id"],
            "status": raw["status"],
            "questions": [dict(item) for item in raw["questions"]],
            "answers": raw.get("answers"),
            "source": raw.get("source", "local"),
            "created_at": raw["created_at"],
            "resolved_at": raw["resolved_at"],
        }

    @staticmethod
    def _require_ask(session: dict[str, Any], ask_id: str) -> dict[str, Any]:
        value = str(ask_id or "")
        if not _ASK_ID.fullmatch(value):
            raise ValueError("Invalid Chat Ask id")
        ask = session.get("ask")
        if not isinstance(ask, dict) or ask.get("ask_id") != value:
            raise ValueError("Chat Ask does not exist")
        return ask

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
    def _trim_turn_requests(state: dict[str, Any]) -> None:
        requests = state["turn_requests"]
        if len(requests) <= TURN_REQUEST_LIMIT:
            return
        for key in list(requests):
            if len(requests) <= TURN_REQUEST_LIMIT:
                break
            if requests[key]["status"] in {"completed", "failed", "cancelled"}:
                del requests[key]


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
    def _require_queue_item(session: dict[str, Any], queue_id: str) -> dict[str, Any]:
        value = str(queue_id or "")
        if not _QUEUE_ID.fullmatch(value):
            raise ValueError("Invalid Chat Queue id")
        for row in session["queue"]:
            if row["queue_id"] == value:
                return row
        raise ValueError("Chat Queue item does not exist")

    @staticmethod
    def _queue_snapshot(session: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": session["session_id"],
            "items": [
                {
                    "queue_id": row["queue_id"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                    "status": row["status"],
                }
                for row in session["queue"]
                if row["status"] == "queued"
            ],
            "dispatching": next(
                (
                    {
                        "queue_id": row["queue_id"],
                        "content": row["content"],
                        "created_at": row["created_at"],
                        "status": row["status"],
                    }
                    for row in session["queue"]
                    if row["status"] == "dispatching"
                ),
                None,
            ),
        }

    @staticmethod
    def _state_path(project: Path) -> Path:
        return project / CHAT_DIR / STATE_FILE

    @staticmethod
    def _messages_path(project: Path, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(str(session_id or "")):
            raise ValueError("Invalid Chat session_id")
        return project / CHAT_DIR / "sessions" / f"{session_id}.jsonl"

    def agent_session(self, project: Path, session_id: str, backend: str) -> str:
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            if str(session.get("agent_backend") or "") != str(backend or ""):
                return ""
            return str(session.get("agent_session_id") or "")

    def set_agent_session(
        self,
        project: Path,
        session_id: str,
        backend: str,
        agent_session_id: str,
    ) -> None:
        value = str(agent_session_id or "").strip()
        if not value:
            return
        with self._lock:
            state = self._load(project)
            session = self._require_session(state, session_id)
            session["agent_backend"] = str(backend or "").strip()
            session["agent_session_id"] = value
            session["updated_at"] = time.time()
            self._write(project, state)

    @staticmethod
    def _public_session(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "queue_count": sum(1 for item in row["queue"] if item["status"] == "queued"),
        }

    @classmethod
    def _snapshot(cls, state: dict[str, Any], *, session_id: str = "") -> dict[str, Any]:
        return {
            "active_session_id": state["active_session_id"],
            "session_id": session_id or state["active_session_id"],
            "sessions": [cls._public_session(row) for row in state["sessions"]],
        }
