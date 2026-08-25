"""Python validator Stage: execute one validator attempt and return its facts."""
from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ...errors import RunnerError
from ...runtime.process_runner import run_process
from .contracts import StageContext, StageResult

ResultHandler = Callable[[StageContext, StageResult], StageResult]


@dataclass(frozen=True)
class PythonValidatorStageSpec:
    name: str
    status: str
    path: str = ""
    detail: str = ""
    run_state: str = ""
    mode: Literal["readonly", "write"] = "write"
    actor: str = "validator"
    tolerate_restored_changes: bool = False
    clear_reports: bool = True
    retry: int | None = None
    result_handler: ResultHandler | None = None


class PythonValidatorStage:
    """Run one Python validator process. It does not retry or choose a route."""

    def __init__(self, spec: PythonValidatorStageSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.status = spec.status
        self.detail = spec.detail
        self.run_state = spec.run_state
        self.mode = spec.mode
        self.actor = spec.actor
        self.tolerate_restored_changes = spec.tolerate_restored_changes
        self.retry = spec.retry

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        if ctx.validator_is_ai and not self.spec.path:
            return StageResult(self.name, "pass", output="FILE_VALIDATION_SKIPPED")
        validator = self._validator(ctx)
        if self.spec.clear_reports:
            clear_validator_reports(ctx.work)
        command = [
            sys.executable,
            str(validator),
            "--project-root",
            str(ctx.root),
            "--state-file",
            str(ctx.state_file),
            *ctx.config.validator_args,
        ]
        try:
            result = run_process(command, ctx.root, ctx.config.validator_timeout)
        except OSError as error:
            raise RunnerError(f"validator failed: {error}") from error
        if result.timed_out:
            detail = "\n".join(item for item in [
                f"validator timeout after {ctx.config.validator_timeout} seconds",
                result.output[-4000:].strip(),
            ] if item)
            raise RunnerError(detail)
        return StageResult(
            self.name,
            "pass" if result.return_code == 0 else "fail",
            output=result.output,
        )

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        if self.spec.result_handler is None:
            return result
        return self.spec.result_handler(ctx, result)

    def _validator(self, ctx: StageContext) -> Path:
        if self.spec.path:
            path = Path(self.spec.path).expanduser()
            if not path.is_absolute():
                path = (ctx.root / path).resolve()
            if not path.is_file():
                raise RunnerError(f"validator not found: {path}")
            return path
        if ctx.validator_path is None:
            raise RunnerError("python validation stage requires a validator path")
        return ctx.validator_path


def clear_validator_reports(work: Path) -> None:
    reports = work / "validator-reports"
    if not reports.exists() and not reports.is_symlink():
        return
    try:
        reports.unlink() if reports.is_symlink() or reports.is_file() else shutil.rmtree(reports)
    except OSError as error:
        raise RunnerError(f"failed to clear validator reports: {error}") from error


PythonValidatorStage.spec_class = PythonValidatorStageSpec

__all__ = ["PythonValidatorStage", "PythonValidatorStageSpec", "clear_validator_reports"]
