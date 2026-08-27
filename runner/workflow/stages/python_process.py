"""Shared subprocess execution for Python-backed Stages."""
from __future__ import annotations

import sys
from pathlib import Path

from ...errors import RunnerError
from ...runtime.process_runner import ProcessResult, run_process
from .contracts import StageContext


def resolve_python_path(ctx: StageContext, value: str, label: str) -> Path:
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
    target = resolve_python_path(ctx, str(path), label)
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


__all__ = ["resolve_python_path", "run_python"]
