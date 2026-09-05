"""Generic out-of-process command Stage."""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ...errors import RunnerError
from .contracts import StageContext, StageResult
from .process_stage import ProcessStage, ProcessStageSpec, resolve_project_file, run_stage_process


@dataclass(frozen=True)
class CommandStageSpec(ProcessStageSpec):
    status: str = "Run command"
    actor: str = "command"
    command: str | list[str] = field(default_factory=list)
    cwd: str = ""
    result_kind: str = "generic"
    clean_work: list[str] | None = None


class CommandStage(ProcessStage):
    spec_class = CommandStageSpec

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
        super().__init__(spec)
        self.result_kind = spec.result_kind

    def timeout(self, ctx: StageContext) -> float:
        if self.spec.timeout is not None:
            return float(self.spec.timeout)
        if self.result_kind == "validation":
            return float(ctx.config.validator_timeout)
        return super().timeout(ctx)

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
        return run_stage_process(
            ctx,
            self.name,
            self._command(ctx),
            self.timeout(ctx),
            "command Stage",
            cwd=cwd,
        )

    def _command(self, ctx: StageContext) -> list[str]:
        mapping = {
            "{python}": sys.executable,
            "{project_root}": str(ctx.root),
            "{work_dir}": str(ctx.work),
            "{state_file}": str(ctx.state_file),
        }
        values = (
            _split_command(self.spec.command)
            if isinstance(self.spec.command, str)
            else self.spec.command
        )
        result: list[str] = []
        for value in values:
            if value == "{validator_args}":
                result.extend(ctx.config.validator_args)
                continue
            if value == "{validator}":
                if ctx.validator_path is None:
                    raise RunnerError("command validator requires a validator path")
                result.append(str(resolve_project_file(ctx, ctx.validator_path, "validator")))
                continue
            result.append(mapping.get(value, value))
        return result


def _split_command(command: str) -> list[str]:
    parts = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        parts = [
            value[1:-1]
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"
            else value
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
