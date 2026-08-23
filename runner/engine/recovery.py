"""Deterministic stage outcome classification and recovery policy."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..config.defaults import NO_PROGRESS_LIMIT
from ..errors import RunnerError, diagnostic_error
from ..runtime.project_state import progress_key
from .models import Task

OutcomeClass = Literal[
    "success",
    "valid_failure",
    "transient",
    "session",
    "stagnation",
    "infrastructure",
]


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
    data: object | None = None


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


def _is_session_error(error: BaseException) -> bool:
    cause = diagnostic_error(error)
    diagnostics = getattr(cause, "diagnostics", {}) if cause is not None else {}
    return bool(diagnostics.get("loop_type"))


def _stalled(task: Task, threshold: int) -> bool:
    limit = min(NO_PROGRESS_LIMIT, threshold) if threshold else NO_PROGRESS_LIMIT
    return task.stagnant_attempts >= limit


def classify(outcome: Outcome, task: Task | None = None, threshold: int = 0) -> OutcomeClass:
    """Normalize stage-specific results without hiding domain fallback semantics."""
    if outcome.status == "pass":
        return "success"
    if outcome.status == "fail":
        return "valid_failure"
    if outcome.error is not None and is_service_error(outcome.error):
        return "transient"
    if task is not None and _stalled(task, threshold):
        return "stagnation"
    if outcome.stage == "validate":
        return "infrastructure"
    if outcome.error is not None and _is_session_error(outcome.error):
        return "session"
    return "session" if outcome.stage in {"planning", "execute", "review"} else "infrastructure"


def record_execution_progress(task: Task, error: RunnerError, changed: bool) -> None:
    """Only repeated identical task evidence counts toward recovery escalation."""
    if changed:
        reset_task_recovery(task)
        return
    if is_service_error(error):
        return
    key = error_failure_key(error)
    if key == task.progress_key:
        task.stagnant_attempts += 1
    else:
        task.progress_key = key
        task.stagnant_attempts = 1
        task.recovery_level = 0


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
        task.recovery_level = 0


def reset_task_recovery(task: Task) -> None:
    task.progress_key = ""
    task.stagnant_attempts = 0
    task.recovery_level = 0


def escalate_task_recovery(task: Task) -> None:
    task.recovery_level = 1
    task.stagnant_attempts = 0


def decide(
    outcome: Outcome,
    *,
    task: Task | None = None,
    threshold: int = 0,
    recovery_level: int = 0,
) -> Transition:
    """Choose ADVANCE / RETRY / REPLAN. Recoverable outcomes never STOP the run."""
    category = classify(outcome, task, threshold)

    if outcome.stage == "execute" and (category == "success" or outcome.changed_files):
        return Transition("advance", reason="review executor result")
    if outcome.stage == "review" and category == "success":
        return Transition("advance", reason="task review passed")
    if outcome.stage == "validate":
        if category == "success":
            return Transition("advance", reason="validator passed")
        if category == "valid_failure":
            return Transition("replan", reason="validator rejected current project state")
        return Transition("retry", reason="validator infrastructure failure")
    if outcome.stage == "planning":
        if category == "success":
            return Transition("advance", reason="usable planning result")
        return Transition("retry", "fresh" if recovery_level > 0 else "same", "planning recovery")

    if task is None:
        raise ValueError(f"{outcome.stage} recovery requires task")
    if category == "transient":
        return Transition("retry", reason="transient service failure")
    if category != "stagnation":
        return Transition("retry", reason="task retry")
    if task.recovery_level == 0:
        return Transition("retry", "fresh", "task recovery escalated to fresh session")
    return Transition("replan", reason="task recovery escalated to replan")


__all__ = [
    "Outcome",
    "OutcomeClass",
    "Transition",
    "classify",
    "decide",
    "error_failure_key",
    "escalate_task_recovery",
    "is_service_error",
    "record_execution_progress",
    "record_review_progress",
    "reset_task_recovery",
    "validator_failure_key",
]
