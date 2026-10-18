"""Ordinary Project Chat execution service."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
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
    ) -> dict[str, Any]:
        text = str(message or "").strip()
        if not text:
            raise ValueError("Chat message is empty")
        if mode not in {"read", "auto", "yolo"}:
            raise ValueError("Unsupported Chat mode")
        agent = str(backend or "").strip()
        if not agent:
            raise ValueError("Chat Agent is required")

        key = (str(project.resolve()), str(session_id))
        lock = self._lock_for(key)
        if not lock.acquire(blocking=False):
            raise ValueError("This Chat already has an Agent turn in progress")
        try:
            previous_session = chat.agent_session(project, session_id, agent)
            user = chat.append_message(project, session_id, "user", text)
            result = self._runner(
                project=project,
                backend=agent,
                model=str(model or "").strip(),
                mode=mode,
                session_id=previous_session,
                prompt=text,
            )
            answer = str(result.get("text") or "").strip()
            if not answer:
                raise RuntimeError("Chat Agent returned an empty response")
            next_session = str(result.get("session_id") or previous_session).strip()
            if next_session:
                chat.set_agent_session(project, session_id, agent, next_session)
            assistant = chat.append_message(project, session_id, "assistant", answer)
            return {
                "session_id": session_id,
                "agent": agent,
                "model": str(model or "").strip(),
                "mode": mode,
                "messages": [user, assistant],
            }
        finally:
            lock.release()

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
