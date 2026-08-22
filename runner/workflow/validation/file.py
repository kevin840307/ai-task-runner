"""Deterministic external validator execution and report cleanup."""
from __future__ import annotations

import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from ...errors import RunnerError
from ...process_control import run_process
from ...safety.project_guard import restore_changed, snapshot


def run_file_validator(
    path: Path,
    root: Path,
    state_file: Path,
    timeout: int,
    extra_args: Sequence[str],
    protected: Sequence[Path],
) -> tuple[bool, str]:
    file_snapshot = snapshot(protected)
    clear_validator_reports(root)
    command = [
        sys.executable,
        str(path),
        "--project-root",
        str(root),
        "--state-file",
        str(state_file),
        *extra_args,
    ]
    try:
        result = run_process(command, root, timeout)
    except OSError as error:
        restore_changed(file_snapshot)
        raise RunnerError(f"validator failed: {error}") from error

    changed = restore_changed(file_snapshot)
    changed_message = (
        "Protected file changed during validation and was restored: "
        + ", ".join(changed)
        if changed
        else ""
    )
    if result.timed_out:
        details = [
            f"validator timeout after {timeout} seconds",
            result.output[-4000:].strip(),
            changed_message,
        ]
        raise RunnerError("\n".join(item for item in details if item))
    if changed_message:
        raise RunnerError(changed_message)
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
