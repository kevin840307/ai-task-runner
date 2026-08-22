"""Persistent runner state loading, recovery, and atomic saves."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS
from .errors import RunnerError
from .models import RunState
from .agent.prompts import bounded_text


JSON_WRITE_RETRIES = 10
JSON_WRITE_RETRY_DELAY = 0.05


def _write_json(path: Path, data: Any) -> None:
    """Atomically write indented UTF-8 JSON with Windows lock tolerance."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for attempt in range(JSON_WRITE_RETRIES):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == JSON_WRITE_RETRIES - 1:
                raise
            time.sleep(JSON_WRITE_RETRY_DELAY * (attempt + 1))


@dataclass(frozen=True)
class StateStore:
    root: Path
    work: Path

    @property
    def path(self) -> Path:
        return self.work / "state.json"

    @property
    def backup_path(self) -> Path:
        key = hashlib.sha256(
            str(self.work).lower().encode("utf-8")
        ).hexdigest()[:24]
        return (
            Path(tempfile.gettempdir())
            / "ai-task-runner-state"
            / key
            / "state.json"
        )

    def load_or_create(
        self,
        goal: str,
        *,
        resume: bool,
        force_new: bool,
    ) -> RunState:
        if resume:
            self.restore_backup()
            return self._load_resume_state()
        if not goal:
            raise RunnerError("--goal is required")
        if self.path.exists() and not force_new:
            raise RunnerError("state exists; use --resume or --force-new")
        return RunState(
            run_id=str(uuid.uuid4()),
            goal=goal,
            project_root=str(self.root),
        )

    def save(self, state: RunState) -> None:
        data = state.dump()
        _write_json(self.path, data)
        _write_json(self.backup_path, data)

    def restore_backup(self) -> None:
        loaded = self._read_state(self.backup_path, strict=False)
        if loaded is None:
            return
        payload, state = loaded
        if Path(state.project_root).resolve() == self.root:
            _write_json(self.path, payload)

    def _load_resume_state(self) -> RunState:
        if not self.path.is_file():
            raise RunnerError(f"resume state not found: {self.path}")
        loaded = self._read_state(self.path, strict=True)
        assert loaded is not None
        _, state = loaded
        if Path(state.project_root).resolve() != self.root:
            raise RunnerError("resume state belongs to a different project_root")
        state.validator_output = bounded_text(
            state.validator_output,
            MAX_VALIDATOR_OUTPUT_CHARS,
        )
        for task in state.tasks:
            task.last_output = task.last_output[-MAX_TASK_OUTPUT_CHARS:]
        return state

    @staticmethod
    def _read_state(
        path: Path,
        *,
        strict: bool,
    ) -> tuple[dict[str, Any], RunState] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            state = RunState.load(payload)
            return payload, state
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            if strict:
                raise RunnerError(f"invalid resume state: {error}") from error
            return None
