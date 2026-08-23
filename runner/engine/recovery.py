"""Deterministic retry and session-recovery policy helpers."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..config.defaults import NO_PROGRESS_LIMIT
from ..errors import RunnerError
from ..safety.project_guard import progress_key
from .models import ExecutionOutcome, Task


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



def is_service_error(error: BaseException) -> bool:
    """Return True for transient external service/API failures in an error chain."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if bool(getattr(current, "transient", False)):
            return True
        current = current.__cause__ or current.__context__
    return False


def execution_outcome(
    *,
    output: str = "",
    error: RunnerError | None = None,
    changed_files: list[str] | None = None,
) -> ExecutionOutcome:
    """Normalize executor completion without encoding backend-specific error kinds."""
    return ExecutionOutcome(
        status=(
            "normal"
            if error is None
            else "service_error"
            if is_service_error(error)
            else "execution_error"
        ),
        output=output,
        error=error,
        changed_files=list(changed_files or []),
    )


def should_review(outcome: ExecutionOutcome) -> bool:
    """Review successful execution or any failed execution that changed the project."""
    return outcome.status == "normal" or bool(outcome.changed_files)


def record_execution_progress(task: Task, error: RunnerError, changed: bool) -> None:
    """Record whether a failed executor attempt produced new evidence/progress."""
    if changed:
        task.progress_key = ""
        task.stagnant_attempts = 0
        return
    if is_service_error(error):
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


def should_rebuild_session(task: Task, error: RunnerError | None = None) -> bool:
    # External service/API outages are not evidence that the coding session is bad.
    return not (error and is_service_error(error)) and task.stagnant_attempts >= NO_PROGRESS_LIMIT


def task_attempts_exhausted(task: Task, max_attempts: int) -> bool:
    return bool(max_attempts and task.attempts >= max_attempts)


__all__ = [
    "error_failure_key",
    "execution_outcome",
    "is_service_error",
    "record_execution_progress",
    "record_review_progress",
    "should_rebuild_session",
    "should_review",
    "task_attempts_exhausted",
    "validator_failure_key",
]
