"""Single process execution boundary shared by command-backed Stages."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ...errors import RunnerError
from ...runtime.process_runner import run_process
from .contracts import MODE_WRITE, StageContext, StageMode, StageResult


@dataclass(frozen=True)
class ProcessStageSpec:
    name: str
    status: str = "Process Stage"
    detail: str = ""
    run_state: str = ""
    mode: StageMode = MODE_WRITE
    actor: str = "process"
    timeout: float | None = None
    retry: int | None = None
    skip_on_error: bool = False
    track_changes: bool = False
    tolerate_restored_changes: bool = False
    produces: str = ""


class ProcessStage:
    """Common Stage surface for all child-process backed implementations."""

    result_kind = "generic"
    timeout_config_attr = "agent_timeout"
    retry_config_attr = ""

    def __init__(self, spec: ProcessStageSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.status = spec.status
        self.detail = spec.detail
        self.run_state = spec.run_state
        self.mode = spec.mode
        self.actor = spec.actor
        self.retry = spec.retry
        self.skip_on_error = spec.skip_on_error
        self.track_changes = spec.track_changes
        self.tolerate_restored_changes = spec.tolerate_restored_changes

    def retry_limit(self, ctx: StageContext) -> int | None:
        if self.spec.retry is not None:
            return self.spec.retry
        if self.retry_config_attr:
            return int(getattr(ctx.config, self.retry_config_attr))
        return None

    def timeout(self, ctx: StageContext) -> float:
        if self.spec.timeout is not None:
            return float(self.spec.timeout)
        return float(getattr(ctx.config, self.timeout_config_attr))

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        return result


def resolve_project_file(ctx: StageContext, value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (ctx.root / path).resolve()
    if not path.is_file():
        raise RunnerError(f"{label} not found: {path}")
    return path


def run_stage_process(
    ctx: StageContext,
    stage: str,
    command: Sequence[str],
    timeout: int | float,
    label: str,
    *,
    cwd: Path | None = None,
) -> StageResult:
    if not command or any(not isinstance(value, str) or not value for value in command):
        raise RunnerError(f"{label} command must contain non-empty strings")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout < 0:
        raise RunnerError(f"{label} has invalid timeout: {timeout}")
    try:
        result = run_process(list(command), cwd or ctx.root, timeout)
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
    return StageResult(
        stage,
        "pass" if result.return_code == 0 else "fail",
        output=result.output,
    )


__all__ = [
    "ProcessStage",
    "ProcessStageSpec",
    "resolve_project_file",
    "run_stage_process",
]
