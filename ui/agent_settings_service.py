"""Cached Agent settings catalog for Project Chat."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


class AgentSettingsService:
    def __init__(self, repo_root: Path, *, ttl_seconds: float = 20) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._lock = threading.RLock()
        self._cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}

    def get(
        self,
        project: Path,
        backend: str,
        model: str = "",
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        agent = str(backend or "").strip()
        if not agent:
            raise ValueError("Agent is required")
        selected_model = str(model or "").strip()
        key = (str(project.resolve()), agent, selected_model)
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if not refresh and cached and now - cached[0] < self.ttl_seconds:
                return {**cached[1], "cached": True}
        value = self._load(project, agent, selected_model)
        with self._lock:
            self._cache[key] = (time.monotonic(), value)
        return {**value, "cached": False}

    def invalidate(self, project: Path | None = None) -> None:
        project_key = str(project.resolve()) if project is not None else ""
        with self._lock:
            for key in list(self._cache):
                if not project_key or key[0] == project_key:
                    del self._cache[key]

    def _load(self, project: Path, backend: str, model: str) -> dict[str, Any]:
        command = [
            sys.executable,
            str(self.repo_root / "tool" / "agent_settings_catalog.py"),
            "--project-root",
            str(project),
            "--backend",
            backend,
        ]
        if model:
            command.extend(["--model", model])
        try:
            result = subprocess.run(
                command,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=25,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Agent settings catalog unavailable: {exc}") from exc
        raw = result.stdout.strip()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            detail = result.stderr.strip() or raw or f"exit {result.returncode}"
            raise ValueError(f"Agent settings catalog returned invalid JSON: {detail[-2000:]}") from exc
        if result.returncode or payload.get("error"):
            detail = str(payload.get("error") or result.stderr or f"exit {result.returncode}").strip()
            raise ValueError(detail or "Agent settings catalog failed")
        if not isinstance(payload, dict):
            raise ValueError("Agent settings catalog returned invalid payload")
        for key in ("models", "modes", "reasoning"):
            if not isinstance(payload.get(key), list):
                raise ValueError(f"Agent settings catalog is missing {key}")
        if not isinstance(payload.get("features"), dict):
            raise ValueError("Agent settings catalog is missing features")
        return payload
