"""Durable task/run state plus atomic state persistence."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from ..config.defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS
from ..config.runtime import is_integer, is_number
from ..errors import RunnerError
from ..utils import bounded_text

VALID_TASK_STATUSES = frozenset({"pending", "completed"})


@dataclass
class Task:
    id: str
    title: str
    description: str
    acceptance_criteria: list[str] = field(default_factory=list)
    deliverable: str = ""
    status: str = "pending"
    attempts: int = 0
    last_output: str = ""
    last_review: dict[str, Any] | None = None
    review_skipped: bool = False
    review_skip_reason: str = ""
    changed_files: list[str] = field(default_factory=list)

    def validate(self, index: int) -> None:
        prefix = f"tasks[{index}]"
        for name in ("id", "title", "description"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{prefix}.{name} must be a non-empty string")
        if not isinstance(self.acceptance_criteria, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.acceptance_criteria
        ):
            raise ValueError(f"{prefix}.acceptance_criteria must be strings")
        if self.status not in VALID_TASK_STATUSES:
            raise ValueError(f"{prefix}.status is invalid")
        if not isinstance(self.review_skipped, bool):
            raise ValueError(f"{prefix}.review_skipped must be boolean")
        if not isinstance(self.review_skip_reason, str):
            raise ValueError(f"{prefix}.review_skip_reason must be a string")
        if not isinstance(self.changed_files, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.changed_files
        ):
            raise ValueError(f"{prefix}.changed_files must be strings")
        if not is_integer(self.attempts) or self.attempts < 0:
            raise ValueError(f"{prefix}.attempts must be non-negative")


@dataclass
class RunState:
    run_id: str
    goal: str
    project_root: str
    cycle: int = 1
    current: int = 0
    tasks: list[Task] = field(default_factory=list)
    validator_output: str = ""
    completed: bool = False
    ai_session_id: str = ""
    stage: str = "created"
    stage_started_at: float = 0.0
    last_activity_at: float = 0.0
    last_error: str = ""
    validator_failure_key: str = ""
    validator_failure_count: int = 0
    replan_feedback: str = ""
    failure_scope: str = ""
    failure_key: str = ""
    same_failures: int = 0
    fresh_session_round: int = 0

    def dump(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        for name in ("run_id", "goal", "project_root"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"state.{name} must be a non-empty string")
        if not is_integer(self.cycle) or self.cycle < 1:
            raise ValueError("state.cycle must be a positive integer")
        if not is_integer(self.current) or not 0 <= self.current <= len(self.tasks):
            raise ValueError("state.current is outside the task list")
        if not isinstance(self.completed, bool):
            raise ValueError("state.completed must be boolean")
        for name in ("stage", "last_error", "validator_failure_key", "replan_feedback", "failure_scope", "failure_key"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(f"state.{name} must be a string")
        for name in ("stage_started_at", "last_activity_at"):
            value = getattr(self, name)
            if not is_number(value) or value < 0:
                raise ValueError(f"state.{name} must be a non-negative number")
        for name in ("validator_failure_count", "same_failures", "fresh_session_round"):
            value = getattr(self, name)
            if not is_integer(value) or value < 0:
                raise ValueError(f"state.{name} must be non-negative")
        for index, task in enumerate(self.tasks, 1):
            task.validate(index)
        if self.completed and any(task.status != "completed" for task in self.tasks):
            raise ValueError("completed state contains pending tasks")

    @classmethod
    def load(cls, data: dict[str, Any]) -> RunState:
        if not isinstance(data, dict):
            raise ValueError("state must be a JSON object")
        values = dict(data)
        if "ai_session_id" not in values:
            values["ai_session_id"] = values.pop("model_session_id", values.pop("agent_session_id", ""))
        raw_tasks = values.get("tasks", [])
        if not isinstance(raw_tasks, list):
            raise ValueError("state.tasks must be an array")
        tasks: list[Task] = []
        for index, item in enumerate(raw_tasks, 1):
            if not isinstance(item, dict):
                raise ValueError(f"tasks[{index}] must be an object")
            allowed = {field.name for field in fields(Task)}
            tasks.append(Task(**{key: value for key, value in item.items() if key in allowed}))
        values["tasks"] = tasks
        allowed_state = {item.name for item in fields(cls)}
        state = cls(**{key: value for key, value in values.items() if key in allowed_state})
        state.validate()
        return state


# ---- Persistence ---------------------------------------------------------
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


def set_stage(state: RunState, stage: str, detail: str = "", *, now: float | None = None) -> None:
    timestamp = time.time() if now is None else now
    if state.stage != stage:
        state.stage = stage
        state.stage_started_at = timestamp
    state.last_activity_at = timestamp
    state.last_error = detail[-1000:] if detail else ""


def normalize_state(state: RunState) -> bool:
    changed = False
    if state.completed and state.stage != "completed":
        state.completed = False
        changed = True
    if state.current > len(state.tasks):
        state.current = len(state.tasks)
        changed = True
    if state.current < len(state.tasks) and state.tasks[state.current].status == "completed":
        pending = next((i for i, task in enumerate(state.tasks) if task.status != "completed"), len(state.tasks))
        if pending != state.current:
            state.current = pending
            changed = True
    return changed

__all__ = ["RunState", "StateStore", "Task", "normalize_state", "set_stage"]
