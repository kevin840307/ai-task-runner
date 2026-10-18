"""Transient TaskDraft generation service."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from .task_models import DRAFT_MODES, bounded_text, validate_generated_draft

CACHE_LIMIT = 128


class TaskDraftService:
    def __init__(self, repo_root: Path, *, runner: Callable[..., dict[str, Any]] | None = None) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self._runner = runner or self._run_tool
        self._lock = threading.RLock()
        self._requests: dict[tuple[str, str], dict[str, Any]] = {}

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
    ) -> dict[str, Any]:
        mode = str(draft_mode or "").strip().lower()
        if mode not in DRAFT_MODES:
            raise ValueError("Unsupported TaskDraft mode")
        text = bounded_text(spec, "TaskDraft spec", 24000)
        agent = bounded_text(backend, "TaskDraft Agent", 120)
        request = bounded_text(request_id, "request_id", 240)
        key = (str(project.resolve()), request)
        with self._lock:
            cached = self._requests.get(key)
            if cached is not None:
                return {**deepcopy(cached), "duplicate": True}

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
        )
        value = {
            "draft_id": f"draft-{uuid.uuid4().hex}",
            "mode": mode,
            "spec": text,
            "draft": draft,
            "duplicate": False,
        }
        with self._lock:
            self._requests[key] = deepcopy(value)
            while len(self._requests) > CACHE_LIMIT:
                self._requests.pop(next(iter(self._requests)))
        return value

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
                timeout=1860,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"TaskDraft generation failed: {exc}") from exc
        raw = completed.stdout.strip()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            detail = completed.stderr.strip() or raw or f"exit {completed.returncode}"
            raise ValueError(f"TaskDraft generator returned invalid JSON: {detail[-2000:]}") from exc
        if completed.returncode or payload.get("error"):
            detail = str(payload.get("error") or completed.stderr or f"exit {completed.returncode}").strip()
            raise ValueError(detail or "TaskDraft generation failed")
        if not isinstance(payload, dict):
            raise ValueError("TaskDraft generator returned invalid payload")
        return payload
