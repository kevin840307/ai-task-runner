"""Ordinary Project Chat execution service."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tool.chat_agent import (
    chat_features,
    ensure_native_session,
    normalize_ask_request,
    pending_native_ask,
    resolve_native_ask,
)

from .chat_service import ChatService


class ChatTurnCancelled(RuntimeError):
    """The user explicitly stopped the active ordinary Chat turn."""


class ChatAgentService:
    """Coordinate one Agent turn without creating or touching Runner Tasks."""

    def __init__(
        self,
        repo_root: Path,
        *,
        runner: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self._runner = runner
        self._locks_guard = threading.Lock()
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._turn_guard = threading.Lock()
        self._active_processes: dict[tuple[str, str], subprocess.Popen[str]] = {}
        self._cancelled_turns: set[tuple[str, str]] = set()
        self._ask_resolution_guard = threading.Lock()
        self._ask_resolutions: set[tuple[str, str, str, str]] = set()

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
        key = self._turn_key(project, session_id)
        lock = self._lock_for(key)
        metadata = {
            "agent": agent,
            "model": str(model or "").strip(),
            "mode": mode,
            "reasoning": str(reasoning or "").strip(),
        }
        pending_ask = self._recover_stale_ask(project, chat, session_id)
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
        pending_ask = self._recover_stale_ask(project, chat, session_id)
        if isinstance(pending_ask, dict) and pending_ask.get("status") == "waiting":
            return {
                **chat.queue(project, session_id),
                "status": "waiting_ask",
                "busy": True,
                "waiting_ask": True,
            }
        key = self._turn_key(project, session_id)
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
        key = self._turn_key(project, session_id)
        lock = self._lock_for(key)
        snapshot = chat.queue(project, session_id)
        pending_ask = self._recover_stale_ask(project, chat, session_id)
        waiting_ask = isinstance(pending_ask, dict) and pending_ask.get("status") == "waiting"
        busy = lock.locked() or waiting_ask
        return {
            **snapshot,
            "status": "waiting_ask" if waiting_ask else ("busy" if lock.locked() else "idle"),
            "busy": busy,
            "waiting_ask": waiting_ask,
        }

    def cancel_turn(
        self,
        project: Path,
        chat: ChatService,
        *,
        session_id: str,
    ) -> dict[str, Any]:
        key = self._turn_key(project, session_id)
        lock = self._lock_for(key)
        pending = self._recover_stale_ask(project, chat, session_id)
        ask_cancelled = False
        if isinstance(pending, dict) and pending.get("status") == "waiting":
            result = self._complete_ask(
                project,
                chat,
                session_id=session_id,
                ask_id=str(pending["ask_id"]),
                request_id=f"turn-cancel-{pending['ask_id']}",
                cancelled=True,
            )
            ask_cancelled = result.get("ask", {}).get("status") == "cancelled"

        active = lock.locked()
        duplicate = False
        process: subprocess.Popen[str] | None = None
        if active:
            with self._turn_guard:
                duplicate = key in self._cancelled_turns
                self._cancelled_turns.add(key)
                process = self._active_processes.get(key)
            if process is not None:
                self._signal_cancel(process)

        return {
            **chat.queue(project, session_id),
            "status": "cancelling" if active else ("cancelled" if ask_cancelled else "idle"),
            "busy": active,
            "cancelled": active or ask_cancelled,
            "duplicate": duplicate,
        }

    def _drain_locked(
        self,
        project: Path,
        chat: ChatService,
        session_id: str,
    ) -> dict[str, Any]:
        chat.recover_dispatching(project, session_id)
        key = self._turn_key(project, session_id)
        processed: list[str] = []
        cancelled: list[str] = []
        failure = ""
        try:
            while True:
                item = chat.claim_next(project, session_id)
                if item is None:
                    break
                try:
                    self._execute_item(project, chat, session_id, item)
                except ChatTurnCancelled:
                    chat.append_message(
                        project,
                        session_id,
                        "system",
                        "Agent turn cancelled.",
                    )
                    chat.complete_queue_item(
                        project,
                        session_id,
                        item["queue_id"],
                        outcome="cancelled",
                    )
                    cancelled.append(item["queue_id"])
                    self._clear_turn_cancel(key)
                    continue
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
        finally:
            self._clear_turn_cancel(key)
        return {
            **chat.queue(project, session_id),
            "status": "error" if failure else "idle",
            "busy": False,
            "processed": processed,
            "cancelled": cancelled,
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
        turn_key = self._turn_key(project, session_id)
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
                turn_key=turn_key,
            )
        else:
            result = self._invoke_runner(
                turn_key,
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
        turn_key: tuple[str, str],
    ) -> dict[str, Any]:
        result_box: dict[str, Any] = {}
        done = threading.Event()

        def worker() -> None:
            try:
                result_box["value"] = self._invoke_runner(
                    turn_key,
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
            if self._is_turn_cancelled(turn_key):
                continue
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

    def _resolution_key(
        self,
        project: Path,
        session_id: str,
        ask_id: str,
        request_id: str,
    ) -> tuple[str, str, str, str]:
        return (
            str(project.resolve()),
            str(session_id),
            str(ask_id),
            str(request_id),
        )

    def _recover_stale_ask(
        self,
        project: Path,
        chat: ChatService,
        session_id: str,
    ) -> dict[str, Any] | None:
        pending = chat.ask(project, session_id).get("ask")
        if not isinstance(pending, dict):
            return pending
        if pending.get("status") == "resolving":
            context = chat.ask_context(
                project,
                session_id,
                str(pending.get("ask_id") or ""),
            )
            key = self._resolution_key(
                project,
                session_id,
                context["ask_id"],
                str(context.get("answer_request_id") or ""),
            )
            with self._ask_resolution_guard:
                active = key in self._ask_resolutions
            if active:
                return pending
            pending = chat.recover_ask_resolution(
                project,
                session_id,
                context["ask_id"],
            ).get("ask")
        if (
            isinstance(pending, dict)
            and pending.get("status") == "waiting"
            and float(pending.get("expires_at") or 0.0) > 0.0
            and float(pending["expires_at"]) <= time.time()
        ):
            request_id = f"timeout-{pending['ask_id']}"
            result = self._complete_ask(
                project,
                chat,
                session_id=session_id,
                ask_id=str(pending["ask_id"]),
                request_id=request_id,
                cancelled=True,
            )
            if not result.get("duplicate"):
                chat.append_message(
                    project,
                    session_id,
                    "system",
                    "Ask timed out; the pending Agent question was cancelled.",
                )
            return result.get("ask")
        return pending

    def complete_ask(
        self,
        project: Path,
        chat: ChatService,
        *,
        session_id: str,
        ask_id: str,
        request_id: str,
        answers: Any = None,
        cancelled: bool = False,
    ) -> dict[str, Any]:
        self._recover_stale_ask(project, chat, session_id)
        return self._complete_ask(
            project,
            chat,
            session_id=session_id,
            ask_id=ask_id,
            request_id=request_id,
            answers=answers,
            cancelled=cancelled,
        )

    def _complete_ask(
        self,
        project: Path,
        chat: ChatService,
        *,
        session_id: str,
        ask_id: str,
        request_id: str,
        answers: Any = None,
        cancelled: bool = False,
    ) -> dict[str, Any]:
        key = self._resolution_key(
            project,
            session_id,
            ask_id,
            request_id,
        )
        with self._ask_resolution_guard:
            owned = key not in self._ask_resolutions
            if owned:
                self._ask_resolutions.add(key)
        try:
            started = chat.begin_ask_resolution(
                project,
                session_id,
                ask_id,
                answers,
                request_id=request_id,
                cancelled=cancelled,
            )
            if started.get("duplicate"):
                return started
            try:
                self.resolve_ask(
                    project,
                    chat,
                    session_id=session_id,
                    ask_id=ask_id,
                    cancelled=cancelled,
                )
            except Exception:
                chat.abort_ask_resolution(
                    project,
                    session_id,
                    ask_id,
                    request_id=request_id,
                )
                raise
            return chat.finish_ask_resolution(
                project,
                session_id,
                ask_id,
                request_id=request_id,
            )
        finally:
            if owned:
                with self._ask_resolution_guard:
                    self._ask_resolutions.discard(key)

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
            if cancelled:
                return
            raise RuntimeError(
                "Native Ask is no longer pending in the Agent service"
            )
        if self._native_request_id(payload) != native_request:
            if cancelled:
                return
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

    @staticmethod
    def _turn_key(project: Path, session_id: str) -> tuple[str, str]:
        return (str(project.resolve()), str(session_id))

    def _invoke_runner(
        self,
        turn_key: tuple[str, str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self._is_turn_cancelled(turn_key):
            raise ChatTurnCancelled()
        if self._runner is None:
            result = self._run_tool(turn_key=turn_key, **kwargs)
        else:
            result = self._runner(**kwargs)
        if self._is_turn_cancelled(turn_key):
            raise ChatTurnCancelled()
        return result

    def _is_turn_cancelled(self, key: tuple[str, str]) -> bool:
        with self._turn_guard:
            return key in self._cancelled_turns

    def _clear_turn_cancel(self, key: tuple[str, str]) -> None:
        with self._turn_guard:
            self._cancelled_turns.discard(key)

    @staticmethod
    def _signal_cancel(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()
        except OSError:
            pass

    def _lock_for(self, key: tuple[str, str]) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def _run_tool(
        self,
        *,
        turn_key: tuple[str, str],
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
        options: dict[str, Any] = {
            "cwd": self.repo_root,
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        process = subprocess.Popen(command, **options)
        with self._turn_guard:
            self._active_processes[turn_key] = process
            cancel_now = turn_key in self._cancelled_turns
        if cancel_now:
            self._signal_cancel(process)
        try:
            stdout, stderr = process.communicate(input=prompt, timeout=7260)
        except subprocess.TimeoutExpired as exc:
            self._signal_cancel(process)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise RuntimeError("Chat Agent timed out after 7260 seconds") from exc
        finally:
            with self._turn_guard:
                if self._active_processes.get(turn_key) is process:
                    self._active_processes.pop(turn_key, None)

        if self._is_turn_cancelled(turn_key):
            raise ChatTurnCancelled()
        raw = stdout.strip()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            detail = stderr.strip() or raw or f"exit {process.returncode}"
            raise RuntimeError(f"Chat Agent returned invalid output: {detail[-2000:]}") from exc
        if process.returncode or payload.get("error"):
            detail = str(
                payload.get("error")
                or stderr
                or f"exit {process.returncode}"
            ).strip()
            raise RuntimeError(detail or "Chat Agent failed")
        if not isinstance(payload, dict):
            raise RuntimeError("Chat Agent returned invalid result")
        return payload
