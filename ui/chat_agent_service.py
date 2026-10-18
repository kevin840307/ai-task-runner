"""Ordinary Project Chat execution service."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .chat_service import ChatService


class ChatAgentService:
    """Coordinate one Agent turn without creating or touching Runner Tasks."""

    def __init__(
        self,
        repo_root: Path,
        *,
        runner: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self._runner = runner or self._run_tool
        self._locks_guard = threading.Lock()
        self._locks: dict[tuple[str, str], threading.Lock] = {}

    def turn(
        self,
        project: Path,
        chat: ChatService,
        *,
        session_id: str,
        message: str,
        backend: str,
        model: str = "",
        mode: str = "auto",
        reasoning: str = "",
        request_id: str = "",
    ) -> dict[str, Any]:
        text = str(message or "").strip()
        if not text:
            raise ValueError("Chat message is empty")
        if mode not in {"read", "auto", "yolo"}:
            raise ValueError("Unsupported Chat mode")
        agent = str(backend or "").strip()
        if not agent:
            raise ValueError("Chat Agent is required")
        request = str(request_id or "").strip() or f"direct-{uuid.uuid4().hex}"
        queued = chat.enqueue_turn(
            project,
            session_id,
            text,
            request_id=request,
            backend=agent,
            model=str(model or "").strip(),
            mode=mode,
            reasoning=str(reasoning or "").strip(),
        )
        key = (str(project.resolve()), str(session_id))
        lock = self._lock_for(key)
        metadata = {
            "agent": agent,
            "model": str(model or "").strip(),
            "mode": mode,
            "reasoning": str(reasoning or "").strip(),
        }
        pending_ask = chat.ask(project, session_id).get("ask")
        if isinstance(pending_ask, dict) and pending_ask.get("status") == "waiting":
            return {
                **queued,
                **metadata,
                "status": "waiting_ask",
                "busy": True,
                "waiting_ask": True,
            }
        if not lock.acquire(blocking=False):
            return {
                **queued,
                **metadata,
                "status": "queued",
                "busy": True,
            }
        try:
            return {
                **self._drain_locked(project, chat, session_id),
                **metadata,
            }
        finally:
            lock.release()

    def drain(
        self,
        project: Path,
        chat: ChatService,
        *,
        session_id: str,
    ) -> dict[str, Any]:
        pending_ask = chat.ask(project, session_id).get("ask")
        if isinstance(pending_ask, dict) and pending_ask.get("status") == "waiting":
            return {
                **chat.queue(project, session_id),
                "status": "waiting_ask",
                "busy": True,
                "waiting_ask": True,
            }
        key = (str(project.resolve()), str(session_id))
        lock = self._lock_for(key)
        if not lock.acquire(blocking=False):
            return {**chat.queue(project, session_id), "status": "busy", "busy": True}
        try:
            return self._drain_locked(project, chat, session_id)
        finally:
            lock.release()

    def status(
        self,
        project: Path,
        chat: ChatService,
        *,
        session_id: str,
    ) -> dict[str, Any]:
        key = (str(project.resolve()), str(session_id))
        lock = self._lock_for(key)
        snapshot = chat.queue(project, session_id)
        pending_ask = chat.ask(project, session_id).get("ask")
        waiting_ask = isinstance(pending_ask, dict) and pending_ask.get("status") == "waiting"
        busy = lock.locked() or waiting_ask
        return {
            **snapshot,
            "status": "waiting_ask" if waiting_ask else ("busy" if lock.locked() else "idle"),
            "busy": busy,
            "waiting_ask": waiting_ask,
        }

    def _drain_locked(
        self,
        project: Path,
        chat: ChatService,
        session_id: str,
    ) -> dict[str, Any]:
        chat.recover_processing(project, session_id)
        processed: list[str] = []
        failure = ""
        while True:
            item = chat.claim_next(project, session_id)
            if item is None:
                break
            try:
                self._execute_item(project, chat, session_id, item)
            except Exception as exc:
                failure = str(exc) or exc.__class__.__name__
                chat.append_message(
                    project,
                    session_id,
                    "system",
                    f"Agent error: {failure}",
                )
                chat.complete_queue_item(
                    project,
                    session_id,
                    item["queue_id"],
                    outcome="failed",
                )
                break
            chat.complete_queue_item(project, session_id, item["queue_id"])
            processed.append(item["queue_id"])
        return {
            **chat.queue(project, session_id),
            "status": "error" if failure else "idle",
            "busy": False,
            "processed": processed,
            "error": failure,
        }

    def _execute_item(
        self,
        project: Path,
        chat: ChatService,
        session_id: str,
        item: dict[str, Any],
    ) -> None:
        agent = str(item.get("backend") or "").strip()
        if not agent:
            raise ValueError("Queued Chat turn is missing Agent")
        mode = str(item.get("mode") or "auto")
        if mode not in {"read", "auto", "yolo"}:
            raise ValueError("Queued Chat turn has unsupported mode")
        model = str(item.get("model") or "").strip()
        reasoning = str(item.get("reasoning") or "").strip()
        previous_session = chat.agent_session(project, session_id, agent)
        chat.append_message(project, session_id, "user", str(item["content"]))
        result = self._runner(
            project=project,
            backend=agent,
            model=model,
            mode=mode,
            reasoning=reasoning,
            session_id=previous_session,
            prompt=str(item["content"]),
        )
        answer = str(result.get("text") or "").strip()
        if not answer:
            raise RuntimeError("Chat Agent returned an empty response")
        next_session = str(result.get("session_id") or previous_session).strip()
        if next_session:
            chat.set_agent_session(project, session_id, agent, next_session)
        chat.append_message(project, session_id, "assistant", answer)

    def _lock_for(self, key: tuple[str, str]) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def _run_tool(
        self,
        *,
        project: Path,
        backend: str,
        model: str,
        mode: str,
        reasoning: str,
        session_id: str,
        prompt: str,
    ) -> dict[str, Any]:
        command = [
            sys.executable,
            str(self.repo_root / "tool" / "chat_agent.py"),
            "--project-root",
            str(project),
            "--backend",
            backend,
            "--mode",
            mode,
        ]
        if model:
            command.extend(["--model", model])
        if reasoning:
            command.extend(["--reasoning", reasoning])
        if session_id:
            command.extend(["--session", session_id])
        completed = subprocess.run(
            command,
            cwd=self.repo_root,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=7260,
            check=False,
        )
        raw = completed.stdout.strip()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            detail = completed.stderr.strip() or raw or f"exit {completed.returncode}"
            raise RuntimeError(f"Chat Agent returned invalid output: {detail[-2000:]}") from exc
        if completed.returncode or payload.get("error"):
            detail = str(
                payload.get("error")
                or completed.stderr
                or f"exit {completed.returncode}"
            ).strip()
            raise RuntimeError(detail or "Chat Agent failed")
        if not isinstance(payload, dict):
            raise RuntimeError("Chat Agent returned invalid result")
        return payload
