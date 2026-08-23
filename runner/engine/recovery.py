"""Deterministic retry and session-recovery policy helpers."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..config.defaults import NO_PROGRESS_LIMIT
from ..errors import RunnerError
from ..safety.project_guard import progress_key
from .models import Task


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def error_failure_key(error: RunnerError) -> str:
    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    return _digest(lines[-1] if lines else type(error).__name__)


def validator_failure_key(output: str) -> str:
    normalized = "\n".join(
        line.strip() for line in output.splitlines() if line.strip()
    )
    return _digest(normalized)


def record_execution_progress(task: Task, error: RunnerError, changed: bool) -> None:
    """Record whether a failed executor attempt produced new evidence/progress."""
    if changed:
        task.progress_key = ""
        task.stagnant_attempts = 0
        return
    key = error_failure_key(error)
    if key == task.progress_key:
        task.stagnant_attempts += 1
    else:
        task.progress_key = key
        task.stagnant_attempts = 1


def record_review_progress(
    task: Task,
    root: Path,
    work: Path,
    missing_items: list[str],
) -> None:
    key = progress_key(root, work, missing_items)
    if key == task.progress_key:
        task.stagnant_attempts += 1
    else:
        task.progress_key = key
        task.stagnant_attempts = 1


def should_rebuild_session(task: Task) -> bool:
    return task.stagnant_attempts >= NO_PROGRESS_LIMIT


def task_attempts_exhausted(task: Task, max_attempts: int) -> bool:
    return bool(max_attempts and task.attempts >= max_attempts)


__all__ = [
    "error_failure_key",
    "record_execution_progress",
    "record_review_progress",
    "should_rebuild_session",
    "task_attempts_exhausted",
    "validator_failure_key",
]
