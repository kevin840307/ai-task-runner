"""Generic out-of-process Python Stage for user/project automation."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ...errors import RunnerError
from .contracts import MODE_WRITE, StageContext, StageMode, StageResult
from .python_process import run_python

ResultHandler = Callable[[StageContext, StageResult], StageResult]


@dataclass(frozen=True)
class PythonScriptStageSpec:
    name: str
    status: str
    path: str
    args: list[str] = field(default_factory=list)
    detail: str = ""
    run_state: str = ""
    mode: StageMode = MODE_WRITE
    actor: str = "python"
    timeout_attr: str = "agent_timeout"
    retry: int | None = None
    tolerate_restored_changes: bool = False
    result_handler: ResultHandler | None = None


class PythonScriptStage:
    """Run one Python script attempt in a child process."""

    spec_class = PythonScriptStageSpec

    def __init__(self, spec: PythonScriptStageSpec) -> None:
        if not isinstance(spec.path, str) or not spec.path.strip():
            raise TypeError("path must be a non-empty string")
        if not isinstance(spec.args, list) or any(
            not isinstance(value, str) or not value for value in spec.args
        ):
            raise TypeError("args must be a list of non-empty strings")
        self.spec = spec
        self.name = spec.name
        self.status = spec.status
        self.detail = spec.detail
        self.run_state = spec.run_state
        self.mode = spec.mode
        self.actor = spec.actor
        self.retry = spec.retry
        self.tolerate_restored_changes = spec.tolerate_restored_changes

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        timeout = getattr(ctx.config, self.spec.timeout_attr, None)
        if not isinstance(timeout, (int, float)):
            raise RunnerError(f"python Stage has invalid timeout_attr: {self.spec.timeout_attr}")
        result = run_python(ctx, self.spec.path, self.spec.args, timeout, "python Stage script")
        return StageResult(
            self.name,
            "pass" if result.return_code == 0 else "fail",
            output=result.output,
        )

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        return self.spec.result_handler(ctx, result) if self.spec.result_handler else result


__all__ = ["PythonScriptStage", "PythonScriptStageSpec"]
