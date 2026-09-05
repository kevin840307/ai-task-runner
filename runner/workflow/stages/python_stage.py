"""Generic out-of-process Python Stage with optional deterministic validation semantics."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ...errors import RunnerError
from ...runtime.process_runner import ProcessResult, run_process
from .contracts import MODE_WRITE, ResultHandler, StageContext, StageMode, StageResult


@dataclass(frozen=True)
class PythonStageSpec:
    name: str
    status: str
    path: str = ""
    args: list[str] = field(default_factory=list)
    detail: str = ""
    run_state: str = ""
    mode: StageMode = MODE_WRITE
    actor: str = "python"
    timeout_attr: str = "agent_timeout"
    validator: str = ""
    clear_reports: bool = True
    retry: int | None = None
    retry_attr: str = ""
    skip_on_error: bool = False
    track_changes: bool = False
    tolerate_restored_changes: bool = False
    result_handler: ResultHandler | None = None


class PythonStage:
    """Run one Python subprocess attempt; ``validator: file`` adds validator conventions."""

    spec_class = PythonStageSpec

    def __init__(self, spec: PythonStageSpec) -> None:
        if spec.validator not in ("", "file"):
            raise TypeError("validator must be empty or 'file'")
        if not isinstance(spec.path, str):
            raise TypeError("path must be a string")
        if not spec.validator and not spec.path.strip():
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
        self.actor = "validator" if spec.validator == "file" and spec.actor == "python" else spec.actor
        self.retry = spec.retry
        self.retry_attr = spec.retry_attr
        self.skip_on_error = spec.skip_on_error
        self.track_changes = spec.track_changes
        self.tolerate_restored_changes = spec.tolerate_restored_changes

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        if self.spec.validator == "file":
            return self._run_validator(ctx)
        timeout = getattr(ctx.config, self.spec.timeout_attr, None)
        if not isinstance(timeout, (int, float)):
            raise RunnerError(f"python Stage has invalid timeout_attr: {self.spec.timeout_attr}")
        result = run_python(ctx, self.spec.path, self.spec.args, timeout, "python Stage script")
        return self._result(result)

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        return self.spec.result_handler(ctx, result) if self.spec.result_handler else result

    def _run_validator(self, ctx: StageContext) -> StageResult:
        if ctx.validator_is_ai and not self.spec.path:
            return StageResult(self.name, "pass", output="FILE_VALIDATION_SKIPPED")
        validator = self.spec.path or ctx.validator_path
        if validator is None:
            raise RunnerError("python validation stage requires a validator path")
        if self.spec.clear_reports:
            clear_validator_reports(ctx.work)
        result = run_python(
            ctx,
            validator,
            [
                "--project-root",
                str(ctx.root),
                "--state-file",
                str(ctx.state_file),
                *ctx.config.validator_args,
                *self.spec.args,
            ],
            ctx.config.validator_timeout,
            "validator",
        )
        return self._result(result)

    def _result(self, result: ProcessResult) -> StageResult:
        return StageResult(
            self.name,
            "pass" if result.return_code == 0 else "fail",
            output=result.output,
        )


def clear_validator_reports(work: Path) -> None:
    reports = work / "validator-reports"
    if not reports.exists() and not reports.is_symlink():
        return
    try:
        reports.unlink() if reports.is_symlink() or reports.is_file() else shutil.rmtree(reports)
    except OSError as error:
        raise RunnerError(f"failed to clear validator reports: {error}") from error


def resolve_python_path(ctx: StageContext, value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (ctx.root / path).resolve()
    if not path.is_file():
        raise RunnerError(f"{label} not found: {path}")
    return path


def run_python(
    ctx: StageContext,
    path: str | Path,
    args: list[str],
    timeout: int | float,
    label: str,
) -> ProcessResult:
    """Run one Python file in a child process and normalize process errors."""
    import sys

    target = resolve_python_path(ctx, path, label)
    try:
        result = run_process([sys.executable, str(target), *args], ctx.root, timeout)
    except OSError as error:
        raise RunnerError(f"{label} failed: {error}") from error
    if result.timed_out:
        detail = "\n".join(
            item
            for item in (
                f"{label} timeout after {timeout} seconds",
                result.output[-4000:].strip(),
            )
            if item
        )
        raise RunnerError(detail)
    return result


__all__ = [
    "PythonStage",
    "PythonStageSpec",
    "clear_validator_reports",
    "resolve_python_path",
    "run_python",
]
