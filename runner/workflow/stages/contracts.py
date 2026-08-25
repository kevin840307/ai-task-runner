"""Small Stage contract shared by every pipeline item."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from ...ai.contracts import AIClientProtocol
from ...config import RuntimeConfig
from ...errors import RunnerError
from ...runtime.run_state import RunState, Task

StageStatus = Literal["pass", "fail", "error", "replan"]


@dataclass(frozen=True)
class StageResult:
    """Facts returned by one Stage execution."""

    stage: str
    status: StageStatus
    output: str = ""
    error: RunnerError | None = None
    changed_files: list[str] = field(default_factory=list)
    skipped: bool = False
    data: object | None = None
    next_steps: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def error_result(cls, stage: str, error: BaseException) -> StageResult:
        runner_error = (
            error if isinstance(error, RunnerError) else RunnerError(str(error))
        )
        return cls(
            stage=stage, status="error", output=str(runner_error), error=runner_error
        )


@dataclass
class StageExecution:
    """Attempt-local execution facts supplied by StageExecutor."""

    change_detected: Callable[[], bool] | None = None
    attempt: int = 1
    retry_mode: Literal["initial", "same", "fresh"] = "initial"
    previous_error: str = ""


@dataclass
class StageContext:
    config: RuntimeConfig
    root: Path
    work: Path
    state: RunState
    ai_client: AIClientProtocol
    state_file: Path
    validator_path: Path | None
    validator_is_ai: bool
    save_state: Callable[[], None]
    set_stage: Callable[[str, str], None]
    scratch: dict[str, Any] = field(default_factory=dict)
    execution: StageExecution = field(default_factory=StageExecution)

    @property
    def task(self) -> Task | None:
        return (
            self.state.tasks[self.state.current]
            if self.state.current < len(self.state.tasks)
            else None
        )

    def require_task(self, stage: str) -> Task:
        task = self.task
        if task is None:
            raise RunnerError(f"{stage} stage requires a pending task")
        return task

    def save_session(self) -> None:
        self.state.ai_session_id = self.ai_client.session_id
        self.save_state()

    def reset_sessions(self) -> None:
        """Drop cached AI sessions so the next call starts fresh."""
        for value in (self.ai_client, *self.scratch.values()):
            if hasattr(value, "session_id"):
                value.session_id = ""
        self.state.ai_session_id = ""
        self.save_state()


class Stage(Protocol):
    name: str
    mode: str
    actor: str
    status: str
    detail: str
    retry: int | None

    def run(
        self, ctx: StageContext, previous: StageResult | None = None
    ) -> StageResult: ...
    def finish(self, ctx: StageContext, result: StageResult) -> StageResult: ...


__all__ = ["Stage", "StageContext", "StageExecution", "StageResult", "StageStatus"]
