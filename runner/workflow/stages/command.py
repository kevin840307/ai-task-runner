"""Generic out-of-process command Stage."""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ...errors import ConfigurationError, RunnerError
from ...runtime.process_runner import run_process
from .contracts import MODE_WRITE, StageContext, StageMode, StageResult


@dataclass(frozen=True)
class CommandStageSpec:
    name: str
    status: str = "Run command"
    detail: str = ""
    run_state: str = ""
    mode: StageMode = MODE_WRITE
    actor: str = "command"
    timeout: float | None = None
    retry: int | None = None
    skip_on_error: bool = False
    track_changes: bool = False
    tolerate_restored_changes: bool = False
    produces: str = ""
    command: str | list[str] = field(default_factory=list)
    cwd: str = ""
    result_kind: str = "generic"
    clean_work: list[str] | None = None


class CommandStage:
    """Run one configured child process and map its exit code to a Stage result."""

    spec_class = CommandStageSpec
    timeout_config_attr = "agent_timeout"
    retry_config_attr = ""

    def __init__(self, spec: CommandStageSpec) -> None:
        if isinstance(spec.command, str):
            if not spec.command.strip():
                raise TypeError("command must be a non-empty string or list of strings")
        elif not isinstance(spec.command, list) or not spec.command or any(
            not isinstance(value, str) or not value for value in spec.command
        ):
            raise TypeError("command must be a non-empty string or list of strings")
        if spec.result_kind not in {"generic", "validation"}:
            raise TypeError("result_kind must be generic or validation")
        if spec.clean_work is not None and (
            not isinstance(spec.clean_work, list)
            or any(not isinstance(value, str) or not value for value in spec.clean_work)
        ):
            raise TypeError("clean_work must be a list of non-empty strings")
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
        self.result_kind = spec.result_kind

    def retry_limit(self, ctx: StageContext) -> int | None:
        if self.spec.retry is not None:
            return self.spec.retry
        return int(getattr(ctx.config, self.retry_config_attr)) if self.retry_config_attr else None

    def timeout(self, ctx: StageContext) -> float:
        if self.spec.timeout is not None:
            return float(self.spec.timeout)
        field = "validator_timeout" if self.result_kind == "validation" else self.timeout_config_attr
        return float(getattr(ctx.config, field))

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        return result

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        cwd = ctx.root
        if self.spec.cwd:
            cwd = Path(self.spec.cwd).expanduser()
            if not cwd.is_absolute():
                cwd = (ctx.root / cwd).resolve()
            if not cwd.is_dir():
                raise RunnerError(f"command cwd not found: {cwd}")
        clean_work = self.spec.clean_work
        if clean_work is None and self.result_kind == "validation":
            clean_work = ["validator-reports"]
        _clean_work_paths(ctx.work, clean_work or [])
        command = self._command(ctx)
        if self.result_kind == "validation" and len(command) >= 2 and Path(command[0]).resolve() == Path(sys.executable).resolve():
            script = Path(command[1]).expanduser()
            if script.is_absolute() and not script.is_file():
                raise ConfigurationError(f"validation script not found: {script}")
        return run_stage_process(ctx, self.name, command, self.timeout(ctx), "command Stage", cwd=cwd)

    def _command(self, ctx: StageContext) -> list[str]:
        mapping = {
            "{python}": sys.executable,
            "{project_root}": str(ctx.root),
            "{work_dir}": str(ctx.work),
            "{state_file}": str(ctx.state_file),
            "{runner_root}": str(Path(__file__).resolve().parents[3]),
        }
        values = _split_command(self.spec.command) if isinstance(self.spec.command, str) else self.spec.command
        result: list[str] = []
        for value in values:
            if value == "{validator_args}":
                result.extend(ctx.config.validator_args)
                continue
            if value == "{validator}":
                if ctx.validator_path is None:
                    raise RunnerError("command validator requires a validator path")
                result.append(str(_project_file(ctx, ctx.validator_path, "validator")))
                continue
            expanded = value
            for placeholder, replacement in mapping.items():
                expanded = expanded.replace(placeholder, replacement)
            result.append(expanded)
        return result


def _project_file(ctx: StageContext, value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (ctx.root / path).resolve()
    if not path.is_file():
        raise RunnerError(f"{label} not found: {path}")
    return path


def run_stage_process(
    ctx: StageContext, stage: str, command: Sequence[str], timeout: int | float, label: str, *, cwd: Path | None = None
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
        detail = "\n".join(item for item in (f"{label} timeout after {timeout} seconds", result.output[-4000:].strip()) if item)
        raise RunnerError(detail)
    return StageResult(stage, "pass" if result.return_code == 0 else "fail", output=result.output)


def _split_command(command: str) -> list[str]:
    parts = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        parts = [
            value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'" else value
            for value in parts
        ]
    return parts


def _clean_work_paths(work: Path, values: list[str]) -> None:
    root = work.resolve()
    for value in values:
        path = (root / value).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise RunnerError(f"clean_work path escapes work directory: {value}") from error
        if not path.exists() and not path.is_symlink():
            continue
        try:
            path.unlink() if path.is_symlink() or path.is_file() else shutil.rmtree(path)
        except OSError as error:
            raise RunnerError(f"failed to clean work path {value}: {error}") from error


__all__ = ["CommandStage", "CommandStageSpec"]
