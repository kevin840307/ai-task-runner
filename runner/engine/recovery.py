"""Deterministic Outcome -> Transition policy for the long-running runner."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..config.defaults import NO_PROGRESS_LIMIT
from ..errors import RunnerError
from ..safety.project_guard import progress_key
from .models import Task


@dataclass(frozen=True)
class Outcome:
    """Facts produced by a workflow stage; never contains next-step policy."""

    stage: Literal["planning", "execute", "review", "validate"]
    status: Literal["pass", "fail", "error"]
    output: str = ""
    error: RunnerError | None = None
    changed_files: list[str] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)
    skipped: bool = False


@dataclass(frozen=True)
class Transition:
    """The runner has only three non-terminal transitions."""

    action: Literal["advance", "retry", "replan"]
    retry_session: Literal["same", "fresh"] = "same"
    reason: str = ""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def error_failure_key(error: RunnerError) -> str:
    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    return _digest(lines[-1] if lines else type(error).__name__)


def validator_failure_key(output: str) -> str:
    normalized = "\n".join(line.strip() for line in output.splitlines() if line.strip())
    return _digest(normalized)


def is_service_error(error: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if bool(getattr(current, "transient", False)):
            return True
        current = current.__cause__ or current.__context__
    return False


def record_execution_progress(task: Task, error: RunnerError, changed: bool) -> None:
    """Service outages do not count as task stagnation; real progress resets it."""
    if changed:
        reset_task_recovery(task)
        return
    if is_service_error(error):
        return
    task.recovery_attempts += 1
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
    task.recovery_attempts += 1
    if key == task.progress_key:
        task.stagnant_attempts += 1
    else:
        task.progress_key = key
        task.stagnant_attempts = 1
        task.recovery_attempts = 1
        task.recovery_level = 0


def reset_task_recovery(task: Task) -> None:
    task.progress_key = ""
    task.stagnant_attempts = 0
    task.recovery_attempts = 0
    task.recovery_level = 0


def escalate_task_recovery(task: Task) -> None:
    task.recovery_level = 1
    task.recovery_attempts = 0
    task.stagnant_attempts = 0


def _retry(task: Task, threshold: int, error: RunnerError | None) -> Transition:
    if error is not None and is_service_error(error):
        return Transition("retry", reason="transient service failure")
    stalled = task.stagnant_attempts >= NO_PROGRESS_LIMIT or bool(
        threshold and task.recovery_attempts >= threshold
    )
    if not stalled:
        return Transition("retry", reason="task retry")
    if task.recovery_level == 0:
        return Transition("retry", "fresh", "task recovery escalated to fresh session")
    return Transition("replan", reason="task recovery escalated to replan")


def decide(
    outcome: Outcome,
    *,
    task: Task | None = None,
    threshold: int = 0,
    recovery_level: int = 0,
) -> Transition:
    """Choose ADVANCE / RETRY / REPLAN. Recoverable outcomes never STOP the run."""
    if outcome.stage == "execute":
        if outcome.status == "pass" or outcome.changed_files:
            return Transition("advance", reason="review executor result")
        if task is None or outcome.error is None:
            raise ValueError("execute recovery requires task and error")
        return _retry(task, threshold, outcome.error)

    if outcome.stage == "review":
        if outcome.status == "pass":
            return Transition("advance", reason="task review passed")
        if task is None:
            raise ValueError("review recovery requires task")
        return _retry(task, threshold, outcome.error)

    if outcome.stage == "validate":
        if outcome.status == "pass":
            return Transition("advance", reason="validator passed")
        if outcome.status == "fail":
            return Transition("replan", reason="validator rejected current project state")
        return Transition("retry", reason="validator infrastructure failure")

    if outcome.status == "pass":
        return Transition("advance", reason="usable planning result")
    return Transition(
        "retry",
        "fresh" if recovery_level > 0 else "same",
        "planning recovery",
    )


__all__ = [
    "Outcome",
    "Transition",
    "decide",
    "error_failure_key",
    "escalate_task_recovery",
    "is_service_error",
    "record_execution_progress",
    "record_review_progress",
    "reset_task_recovery",
    "validator_failure_key",
]
