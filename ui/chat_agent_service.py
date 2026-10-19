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

from runner.agent import (
    chat_features,
    ensure_native_session,
    normalize_ask_request,
    pending_native_ask,
    resolve_native_ask,
)

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
        chat.recover_dispatching(project, session_id)
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
        features = chat_features(agent, project)
        native_bridge = (
            features.ask
            and features.ask_transport == "question_api"
        )
        if native_bridge:
            native_session = ensure_native_session(
                agent,
                project,
                previous_session,
            )
            if not native_session:
                raise RuntimeError(
                    f"{agent} native Ask requires a stable Agent session"
                )
            chat.set_agent_session(project, session_id, agent, native_session)
            result = self._run_with_native_ask_bridge(
                project,
                chat,
                session_id,
                item,
                backend=agent,
                model=model,
                mode=mode,
                reasoning=reasoning,
                native_session=native_session,
            )
        else:
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
        next_session = str(
            result.get("session_id")
            or (native_session if native_bridge else previous_session)
        ).strip()
        if next_session:
            chat.set_agent_session(project, session_id, agent, next_session)
        chat.append_message(project, session_id, "assistant", answer)

    @staticmethod
    def _native_request_id(payload: dict[str, Any]) -> str:
        return str(
            payload.get("id")
            or payload.get("questionID")
            or payload.get("questionId")
            or payload.get("requestID")
            or ""
        ).strip()

    def _run_with_native_ask_bridge(
        self,
        project: Path,
        chat: ChatService,
        session_id: str,
        item: dict[str, Any],
        *,
        backend: str,
        model: str,
        mode: str,
        reasoning: str,
        native_session: str,
    ) -> dict[str, Any]:
        result_box: dict[str, Any] = {}
        done = threading.Event()

        def worker() -> None:
            try:
                result_box["value"] = self._runner(
                    project=project,
                    backend=backend,
                    model=model,
                    mode=mode,
                    reasoning=reasoning,
                    session_id=native_session,
                    prompt=str(item["content"]),
                )
            except BaseException as exc:  # hand back to the owning Chat turn
                result_box["error"] = exc
            finally:
                done.set()

        thread = threading.Thread(
            target=worker,
            name=f"chat-{backend}-turn",
            daemon=True,
        )
        thread.start()
        seen: set[str] = set()
        bridge_error: Exception | None = None
        while not done.wait(0.5):
            try:
                payload = pending_native_ask(
                    backend,
                    project,
                    native_session,
                )
            except Exception:
                # Discovery can be transient while the native client/server changes
                # state. The owning Agent process retains its own timeout/cleanup.
                continue
            if not isinstance(payload, dict):
                continue
            native_request = self._native_request_id(payload)
            if not native_request or native_request in seen:
                continue
            try:
                questions = normalize_ask_request(backend, payload)
                ask_request = "native-" + uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{backend}:{native_session}:{native_request}",
                ).hex
                chat.create_ask(
                    project,
                    session_id,
                    request_id=ask_request,
                    turn_id=str(item.get("request_id") or ask_request),
                    questions=questions,
                    source="native",
                    backend=backend,
                    agent_session_id=native_session,
                    native_request_id=native_request,
                )
                seen.add(native_request)
            except Exception as exc:
                bridge_error = exc
                try:
                    resolve_native_ask(
                        backend,
                        project,
                        native_session,
                        payload,
                        None,
                        cancelled=True,
                    )
                except Exception:
                    pass
                seen.add(native_request)

        thread.join(timeout=1)
        error = result_box.get("error")
        if isinstance(error, BaseException):
            raise error
        if bridge_error is not None:
            raise RuntimeError(
                f"Native Ask bridge failed: {bridge_error}"
            ) from bridge_error
        value = result_box.get("value")
        if not isinstance(value, dict):
            raise RuntimeError("Chat Agent returned invalid result")
        return value

    def resolve_ask(
        self,
        project: Path,
        chat: ChatService,
        *,
        session_id: str,
        ask_id: str,
        cancelled: bool = False,
    ) -> None:
        context = chat.ask_context(project, session_id, ask_id)
        if context.get("source") != "native":
            return
        backend = str(context.get("backend") or "").strip()
        native_session = str(
            context.get("agent_session_id") or ""
        ).strip()
        native_request = str(
            context.get("native_request_id") or ""
        ).strip()
        if not backend or not native_session or not native_request:
            raise RuntimeError("Native Ask context is incomplete")
        payload = pending_native_ask(
            backend,
            project,
            native_session,
        )
        if not isinstance(payload, dict):
            raise RuntimeError(
                "Native Ask is no longer pending in the Agent service"
            )
        if self._native_request_id(payload) != native_request:
            raise RuntimeError(
                "Native Ask request no longer matches the durable Chat state"
            )
        resolve_native_ask(
            backend,
            project,
            native_session,
            payload,
            context.get("answers"),
            cancelled=cancelled,
        )

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
