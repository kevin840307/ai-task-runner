"""Deterministic external validator execution and report cleanup."""
from __future__ import annotations

import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from ...errors import RunnerError
from ...runtime.process_control import run_process
from ...runtime.execution import guarded_call


def run_file_validator(
    path: Path,
    root: Path,
    state_file: Path,
    timeout: int,
    extra_args: Sequence[str],
) -> tuple[bool, str]:
    clear_validator_reports(root)
    command = [
        sys.executable, str(path), "--project-root", str(root),
        "--state-file", str(state_file), *extra_args,
    ]
    try:
        result = guarded_call(
            lambda: run_process(command, root, timeout),
            root, root / ".ai-task-runner", actor="validator",
        )
    except OSError as error:
        raise RunnerError(f"validator failed: {error}") from error
    if result.timed_out:
        details = [
            f"validator timeout after {timeout} seconds",
            result.output[-4000:].strip(),
        ]
        raise RunnerError("\n".join(item for item in details if item))
    return result.return_code == 0, result.output


def clear_validator_reports(root: Path) -> None:
    reports = root / ".ai-task-runner" / "validator-reports"
    if not reports.exists() and not reports.is_symlink():
        return
    try:
        if reports.is_symlink() or reports.is_file():
            reports.unlink()
        else:
            shutil.rmtree(reports)
    except OSError as error:
        raise RunnerError(f"failed to clear validator reports: {error}") from error


__all__ = ["clear_validator_reports", "run_file_validator"]
