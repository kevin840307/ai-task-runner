"""Central deterministic recovery policy for the long-running runner."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..config.defaults import NO_PROGRESS_LIMIT
from ..errors import RunnerError
from ..safety.project_guard import progress_key
from .models import ExecutionOutcome, ReviewResult, Task

RecoveryAction = Literal["retry", "continue", "replan"]


@dataclass(frozen=True)
class RecoveryDecision:
    """One workflow-level decision; mechanisms stay in their owning stages/backends."""

    action: RecoveryAction
    fresh_session: bool = False
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


def record_execution_progress(task: Task, error: RunnerError, changed: bool) -> None:
    """Track task-level progress without treating service outages as task failure."""
    if changed:
        task.progress_key = ""
        task.stagnant_attempts = 0
        task.recovery_attempts = 0
        task.recovery_level = 0
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


def _needs_escalation(task: Task, attempt_threshold: int) -> bool:
    return task.stagnant_attempts >= NO_PROGRESS_LIMIT or bool(
        attempt_threshold and task.recovery_attempts >= attempt_threshold
    )


def decide_task_retry(
    task: Task,
    attempt_threshold: int,
    error: RunnerError | None = None,
) -> RecoveryDecision:
    """Escalate same-session retry -> fresh session -> replan, never stop the run."""
    if error is not None and is_service_error(error):
        return RecoveryDecision("retry", reason="transient service failure")
    if not _needs_escalation(task, attempt_threshold):
        return RecoveryDecision("retry", reason="task retry")
    if task.recovery_level == 0:
        return RecoveryDecision(
            "retry",
            fresh_session=True,
            reason="task recovery escalated to fresh session",
        )
    return RecoveryDecision("replan", reason="task recovery escalated to replan")


def decide_execution(
    task: Task, outcome: ExecutionOutcome, attempt_threshold: int
) -> RecoveryDecision:
    """Preserve changed work for review; otherwise apply the shared retry policy."""
    if outcome.status == "normal" or outcome.changed_files:
        return RecoveryDecision("continue", reason="review executor result")
    assert outcome.error is not None
    return decide_task_retry(task, attempt_threshold, outcome.error)


def decide_review(task: Task, review: ReviewResult, attempt_threshold: int) -> RecoveryDecision:
    if review["completed"] is True:
        return RecoveryDecision("continue", reason="task review passed")
    return decide_task_retry(task, attempt_threshold)


def apply_fresh_session_recovery(task: Task) -> None:
    """Advance recovery level while preserving failure signature for replan detection."""
    task.recovery_level = 1
    task.recovery_attempts = 0
    task.stagnant_attempts = 0


__all__ = [
    "RecoveryAction",
    "RecoveryDecision",
    "apply_fresh_session_recovery",
    "decide_execution",
    "decide_review",
    "decide_task_retry",
    "error_failure_key",
    "execution_outcome",
    "is_service_error",
    "record_execution_progress",
    "record_review_progress",
    "validator_failure_key",
]
