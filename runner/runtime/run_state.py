"""Durable Workflow state plus atomic persistence."""

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
from ..errors import ConfigurationError, RunnerError
from ..utils import append_bounded_log, bounded_text, io_path, same_path
from .events import touch_heartbeat

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
        if not is_integer(self.attempts) or self.attempts < 0:
            raise ValueError(f"{prefix}.attempts must be non-negative")
        if not isinstance(self.changed_files, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.changed_files
        ):
            raise ValueError(f"{prefix}.changed_files must be strings")


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
    workflow_position: int = 0
    task_step: int = 0
    workflow_fingerprint: str = ""
    transition_previous: dict[str, Any] = field(default_factory=dict)
    stage_sessions: dict[str, str] = field(default_factory=dict)
    review_failures: dict[str, int] = field(default_factory=dict)

    def dump(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        for name in ("run_id", "goal", "project_root"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"state.{name} must be a non-empty string")
        for name in ("cycle", "current", "workflow_position", "task_step"):
            value = getattr(self, name)
            if not is_integer(value) or value < 0:
                raise ValueError(f"state.{name} must be non-negative")
        if self.cycle < 1:
            raise ValueError("state.cycle must be positive")
        if self.current > len(self.tasks):
            raise ValueError("state.current is outside the task list")
        if not isinstance(self.completed, bool):
            raise ValueError("state.completed must be boolean")
        for name in ("stage", "last_error", "workflow_fingerprint"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"state.{name} must be a string")
        for name in ("stage_started_at", "last_activity_at"):
            value = getattr(self, name)
            if not is_number(value) or value < 0:
                raise ValueError(f"state.{name} must be a non-negative number")
        if not isinstance(self.transition_previous, dict):
            raise ValueError("state.transition_previous must be an object")
        if not isinstance(self.stage_sessions, dict):
            raise ValueError("state.stage_sessions must be an object")
        if not isinstance(self.review_failures, dict):
            raise ValueError("state.review_failures must be an object")
        for name, value in self.review_failures.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("state.review_failures keys must be non-empty strings")
            if not is_integer(value) or value < 0:
                raise ValueError(f"state.review_failures.{name} must be non-negative")
        for name, value in self.stage_sessions.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("state.stage_sessions keys must be non-empty strings")
            if not isinstance(value, str):
                raise ValueError(f"state.stage_sessions.{name} must be a string")
        for index, task in enumerate(self.tasks, 1):
            task.validate(index)
        if self.completed and any(task.status != "completed" for task in self.tasks):
            raise ValueError("completed state contains pending tasks")

    @classmethod
    def load(cls, data: dict[str, Any]) -> "RunState":
        if not isinstance(data, dict):
            raise ValueError("state must be a JSON object")

        allowed_state = {item.name for item in fields(cls)}
        unknown_state = sorted(set(data) - allowed_state)
        if unknown_state:
            raise ValueError("state contains removed fields: " + ", ".join(unknown_state))

        raw_tasks = data.get("tasks", [])
        if not isinstance(raw_tasks, list):
            raise ValueError("state.tasks must be an array")
        allowed_task = {item.name for item in fields(Task)}
        tasks: list[Task] = []
        for index, item in enumerate(raw_tasks, 1):
            if not isinstance(item, dict):
                raise ValueError(f"tasks[{index}] must be an object")
            unknown_task = sorted(set(item) - allowed_task)
            if unknown_task:
                raise ValueError(
                    f"tasks[{index}] contains removed fields: "
                    + ", ".join(unknown_task)
                )
            tasks.append(Task(**item))

        values = dict(data)
        values["tasks"] = tasks
        state = cls(**values)
        state.validate()
        return state


JSON_WRITE_RETRIES = 10
JSON_WRITE_RETRY_DELAY = 0.05


def _write_json(path: Path, data: Any) -> None:
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    io_path(temporary).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for attempt in range(JSON_WRITE_RETRIES):
        try:
            os.replace(io_path(temporary), io_path(path))
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
        key = hashlib.sha256(str(self.work).lower().encode("utf-8")).hexdigest()[:24]
        return Path(tempfile.gettempdir()) / "ai-task-runner-state" / key / "state.json"

    def load_or_create(
        self,
        goal: str,
        *,
        resume: bool,
        force_new: bool,
    ) -> RunState:
        if resume:
            try:
                return self._load_resume_state()
            except ConfigurationError as primary_error:
                if not self.restore_backup():
                    raise primary_error
                return self._load_resume_state()
        if not goal:
            raise RunnerError("--goal is required")
        if io_path(self.path).exists() and not force_new:
            raise RunnerError("state exists; use --resume or --force-new")
        return RunState(
            run_id=str(uuid.uuid4()),
            goal=goal,
            project_root=str(self.root),
        )

    def save(self, state: RunState) -> None:
        data = state.dump()
        _write_json(self.path, data)
        touch_heartbeat()
        try:
            _write_json(self.backup_path, data)
        except OSError as error:
            append_bounded_log(
                self.work / "state-backup-warning.log",
                (
                    f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                    "WARNING state backup failed; primary state remains authoritative; "
                    f"backup={self.backup_path}; {type(error).__name__}: {error}\n"
                ),
            )

    def restore_backup(self) -> bool:
        loaded = self._read_state(self.backup_path, strict=False)
        if loaded is None:
            return False
        payload, state = loaded
        if not same_path(state.project_root, self.root):
            return False
        _write_json(self.path, payload)
        return True

    def _load_resume_state(self) -> RunState:
        if not io_path(self.path).is_file():
            raise ConfigurationError(f"resume state not found: {self.path}")
        loaded = self._read_state(self.path, strict=True)
        assert loaded is not None
        _, state = loaded
        if not same_path(state.project_root, self.root):
            raise ConfigurationError("resume state belongs to a different project_root")
        state.validator_output = bounded_text(
            state.validator_output, MAX_VALIDATOR_OUTPUT_CHARS
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
            payload = json.loads(io_path(path).read_text(encoding="utf-8"))
            return payload, RunState.load(payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            if strict:
                raise ConfigurationError(f"invalid resume state: {error}") from error
            return None


def set_stage(
    state: RunState,
    stage: str,
    detail: str = "",
    *,
    now: float | None = None,
) -> None:
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
        pending = next(
            (i for i, task in enumerate(state.tasks) if task.status != "completed"),
            len(state.tasks),
        )
        if pending != state.current:
            state.current = pending
            changed = True
    return changed


__all__ = ["RunState", "StateStore", "Task", "normalize_state", "set_stage"]
