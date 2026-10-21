"""Transient TaskDraft generation service."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from tool.task_draft_agent import (
    TASK_DRAFT_AGENT_TIMEOUT_SECONDS,
    TASK_DRAFT_ERROR_CHARS,
    TASK_DRAFT_WRAPPER_GRACE_SECONDS,
)

try:
    from .task_models import (
        DRAFT_MODES,
        bounded_text,
        validate_generated_draft,
        validate_task_draft_for_create,
    )
except ImportError:
    from task_models import (
        DRAFT_MODES,
        bounded_text,
        validate_generated_draft,
        validate_task_draft_for_create,
    )

CACHE_LIMIT = 128
_DRAFT_ID = re.compile(r"^draft-[0-9a-f]{32}$")


class TaskDraftService:
    def __init__(
        self,
        repo_root: Path,
        *,
        runner: Callable[..., dict[str, Any]] | None = None,
        workflow_requirements: Callable[[Path, str], dict[str, Any]] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self._runner = runner or self._run_tool
        self._workflow_requirements = workflow_requirements
        self._lock = threading.RLock()
        self._requests: dict[tuple[str, str, str], str] = {}
        self._drafts: dict[tuple[str, str, str], dict[str, Any]] = {}

    def generate(
        self,
        project: Path,
        *,
        spec: str,
        draft_mode: str,
        backend: str,
        model: str = "",
        reasoning: str = "",
        workflow: str = "",
        request_id: str,
        session_id: str = "",
    ) -> dict[str, Any]:
        mode = str(draft_mode or "").strip().lower()
        if mode not in DRAFT_MODES:
            raise ValueError("Unsupported TaskDraft mode")
        text = bounded_text(spec, "TaskDraft spec", 24000)
        agent = bounded_text(backend, "TaskDraft Agent", 120)
        request = bounded_text(request_id, "request_id", 240)
        session = str(session_id or "").strip()
        key = (str(project.resolve()), session, request)
        with self._lock:
            draft_id = str(self._requests.get(key) or "")
            if draft_id:
                cached = self._drafts.get((key[0], key[1], draft_id))
                if cached is not None:
                    return {**deepcopy(cached), "duplicate": True}
                self._requests.pop(key, None)

        generated = self._runner(
            project=project,
            backend=agent,
            model=str(model or "").strip(),
            reasoning=str(reasoning or "").strip(),
            draft_mode=mode,
            spec=text,
        )
        draft = validate_generated_draft(
            generated.get("draft"),
            mode=mode,
            project=project,
            workflow=str(workflow or "").strip(),
            workflow_requirements=self._workflow_requirements,
        )
        value = {
            "draft_id": f"draft-{uuid.uuid4().hex}",
            "mode": mode,
            "spec": text,
            "session_id": session,
            "draft": draft,
            "duplicate": False,
        }
        with self._lock:
            self._requests[key] = value["draft_id"]
            self._drafts[(key[0], key[1], value["draft_id"])] = deepcopy(value)
            while len(self._requests) > CACHE_LIMIT:
                oldest_key = next(iter(self._requests))
                evicted_id = str(self._requests.pop(oldest_key) or "")
                if evicted_id:
                    self._drafts.pop((oldest_key[0], oldest_key[1], evicted_id), None)
        return value

    @staticmethod
    def _draft_id(value: str) -> str:
        draft_id = str(value or "").strip()
        if not _DRAFT_ID.fullmatch(draft_id):
            raise ValueError("Invalid TaskDraft id")
        return draft_id

    def get(self, project: Path, draft_id: str, *, session_id: str = "") -> dict[str, Any]:
        key = (str(project.resolve()), str(session_id or "").strip(), self._draft_id(draft_id))
        with self._lock:
            value = self._drafts.get(key)
            if value is None:
                raise ValueError("TaskDraft is no longer available")
            return deepcopy(value)

    def update(
        self,
        project: Path,
        draft_id: str,
        draft: Any,
        *,
        session_id: str = "",
    ) -> dict[str, Any]:
        project_key = str(project.resolve())
        session = str(session_id or "").strip()
        key = (project_key, session, self._draft_id(draft_id))
        validated = validate_task_draft_for_create(draft, project, workflow_requirements=self._workflow_requirements)
        with self._lock:
            current = self._drafts.get(key)
            if current is None:
                raise ValueError("TaskDraft is no longer available")
            value = {**current, "draft": deepcopy(validated), "duplicate": False}
            self._drafts[key] = deepcopy(value)
            return deepcopy(value)

    def dismiss(self, project: Path, draft_id: str, *, session_id: str = "") -> dict[str, Any]:
        project_key = str(project.resolve())
        session = str(session_id or "").strip()
        key = (project_key, session, self._draft_id(draft_id))
        with self._lock:
            existed = self._drafts.pop(key, None) is not None
            for request_key, cached_draft_id in list(self._requests.items()):
                if (
                    request_key[0] == project_key
                    and request_key[1] == session
                    and cached_draft_id == key[2]
                ):
                    del self._requests[request_key]
            return {"draft_id": key[2], "dismissed": True, "duplicate": not existed}

    def discard_session(self, project: Path, session_id: str) -> dict[str, Any]:
        project_key = str(project.resolve())
        session = str(session_id or "").strip()
        with self._lock:
            draft_keys = [
                key for key in self._drafts
                if key[0] == project_key and key[1] == session
            ]
            request_keys = [
                key for key in self._requests
                if key[0] == project_key and key[1] == session
            ]
            for key in draft_keys:
                self._drafts.pop(key, None)
            for key in request_keys:
                self._requests.pop(key, None)
            return {
                "session_id": session,
                "drafts_removed": len(draft_keys),
                "requests_removed": len(request_keys),
            }

    def _run_tool(
        self,
        *,
        project: Path,
        backend: str,
        model: str,
        reasoning: str,
        draft_mode: str,
        spec: str,
    ) -> dict[str, Any]:
        command = [
            sys.executable,
            str(self.repo_root / "tool" / "task_draft_agent.py"),
            "--project-root",
            str(project),
            "--backend",
            backend,
            "--draft-mode",
            draft_mode,
        ]
        if model:
            command.extend(["--model", model])
        if reasoning:
            command.extend(["--reasoning", reasoning])
        try:
            completed = subprocess.run(
                command,
                cwd=self.repo_root,
                input=spec,
                text=True,
                capture_output=True,
                timeout=TASK_DRAFT_AGENT_TIMEOUT_SECONDS + TASK_DRAFT_WRAPPER_GRACE_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"TaskDraft generation failed: {exc}") from exc
        raw = completed.stdout.strip()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            detail = completed.stderr.strip() or raw or f"exit {completed.returncode}"
            raise ValueError(
                f"TaskDraft generator returned invalid JSON: {detail[-TASK_DRAFT_ERROR_CHARS:]}"
            ) from exc
        if completed.returncode or payload.get("error"):
            detail = str(payload.get("error") or completed.stderr or f"exit {completed.returncode}").strip()
            detail = detail[-TASK_DRAFT_ERROR_CHARS:] if detail else "TaskDraft generation failed"
            raise ValueError(detail)
        if not isinstance(payload, dict):
            raise ValueError("TaskDraft generator returned invalid payload")
        return payload
