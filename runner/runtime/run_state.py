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
from ..errors import ConfigurationError, RunnerError
from ..utils.text import bounded_text

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
    steps: list[str] = field(default_factory=list)

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
        if not isinstance(self.steps, list) or any(
            not isinstance(item, str) or not item.strip() for item in self.steps
        ):
            raise ValueError(f"{prefix}.steps must be strings")
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
    workflow_position: int = 0
    workflow_fingerprint: str = ""
    flow_result_key: str = ""
    flow_result_count: int = 0
    flow_result_previous: dict[str, Any] = field(default_factory=dict)
    semantic_failure_key: str = ""
    semantic_failure_fingerprint: str = ""
    semantic_failure_count: int = 0
    dynamic_steps: list[dict[str, Any]] = field(default_factory=list)
    dynamic_index: int = 0

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
        for name in (
            "stage",
            "last_error",
            "validator_failure_key",
            "replan_feedback",
            "failure_scope",
            "failure_key",
            "workflow_fingerprint",
            "flow_result_key",
            "semantic_failure_key",
            "semantic_failure_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(f"state.{name} must be a string")
        for name in ("stage_started_at", "last_activity_at"):
            value = getattr(self, name)
            if not is_number(value) or value < 0:
                raise ValueError(f"state.{name} must be a non-negative number")
        for name in ("validator_failure_count", "same_failures", "fresh_session_round", "flow_result_count", "semantic_failure_count"):
            value = getattr(self, name)
            if not is_integer(value) or value < 0:
                raise ValueError(f"state.{name} must be non-negative")
        if not is_integer(self.workflow_position) or self.workflow_position < 0:
            raise ValueError("state.workflow_position must be non-negative")
        if not isinstance(self.flow_result_previous, dict):
            raise ValueError("state.flow_result_previous must be an object")
        if not isinstance(self.dynamic_steps, list) or any(
            not isinstance(item, dict) for item in self.dynamic_steps
        ):
            raise ValueError("state.dynamic_steps must be an array of objects")
        if not is_integer(self.dynamic_index) or not 0 <= self.dynamic_index <= len(self.dynamic_steps):
            raise ValueError("state.dynamic_index is outside dynamic_steps")
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
        legacy_task_workflow = values.pop("task_workflow", None)
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
        if "dynamic_steps" not in values and isinstance(legacy_task_workflow, list) and legacy_task_workflow:
            current = int(values.get("current", 0) or 0)
            dynamic_steps: list[dict[str, Any]] = []
            for task_index in range(current, len(tasks)):
                for step_index, step in enumerate(legacy_task_workflow):
                    if not isinstance(step, dict):
                        continue
                    item = dict(step)
                    item["_task_index"] = task_index
                    item["_task_last"] = step_index == len(legacy_task_workflow) - 1
                    dynamic_steps.append(item)
            values["dynamic_steps"] = dynamic_steps
            values["dynamic_index"] = 0
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
            try:
                return self._load_resume_state()
            except ConfigurationError as primary_error:
                if not self.restore_backup():
                    raise primary_error
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

    def restore_backup(self) -> bool:
        loaded = self._read_state(self.backup_path, strict=False)
        if loaded is None:
            return False
        payload, state = loaded
        if Path(state.project_root).resolve() != self.root:
            return False
        _write_json(self.path, payload)
        return True

    def _load_resume_state(self) -> RunState:
        if not self.path.is_file():
            raise ConfigurationError(f"resume state not found: {self.path}")
        loaded = self._read_state(self.path, strict=True)
        assert loaded is not None
        _, state = loaded
        if Path(state.project_root).resolve() != self.root:
            raise ConfigurationError("resume state belongs to a different project_root")
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
                raise ConfigurationError(f"invalid resume state: {error}") from error
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
