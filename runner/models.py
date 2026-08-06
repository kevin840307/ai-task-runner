"""Canonical task and run-state models persisted by AI Task Runner."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


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
    progress_key: str = ""
    stagnant_attempts: int = 0
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
        for name in ("attempts", "stagnant_attempts"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{prefix}.{name} must be non-negative")


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
    agent_session_id: str = ""
    stage: str = "created"
    stage_started_at: float = 0.0
    last_activity_at: float = 0.0
    last_error: str = ""
    validator_failure_key: str = ""
    validator_failure_count: int = 0

    def dump(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        for name in ("run_id", "goal", "project_root"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"state.{name} must be a non-empty string")
        if not isinstance(self.cycle, int) or self.cycle < 1:
            raise ValueError("state.cycle must be a positive integer")
        if not isinstance(self.current, int) or not 0 <= self.current <= len(self.tasks):
            raise ValueError("state.current is outside the task list")
        if not isinstance(self.completed, bool):
            raise ValueError("state.completed must be boolean")
        for name in ("stage", "last_error", "validator_failure_key"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(f"state.{name} must be a string")
        for name in ("stage_started_at", "last_activity_at"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"state.{name} must be a non-negative number")
        if (
            not isinstance(self.validator_failure_count, int)
            or self.validator_failure_count < 0
        ):
            raise ValueError("state.validator_failure_count must be non-negative")
        for index, task in enumerate(self.tasks, 1):
            task.validate(index)
        if self.completed and any(task.status != "completed" for task in self.tasks):
            raise ValueError("completed state contains pending tasks")

    @classmethod
    def load(cls, data: dict[str, Any]) -> "RunState":
        if not isinstance(data, dict):
            raise ValueError("state must be a JSON object")
        values = dict(data)
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
        state = cls(**values)
        state.validate()
        return state


# Backward-compatible alias used by releases before v1.0.
State = RunState

__all__ = ["RunState", "State", "Task"]
