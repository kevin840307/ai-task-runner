"""Cross-platform subprocess timeout and process-tree cleanup helpers."""
from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


TERMINATION_GRACE_SECONDS = 5
TASKKILL_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class ProcessResult:
    output: str
    return_code: int
    timed_out: bool = False


def run_process(
    command: Sequence[str],
    cwd: Path,
    timeout: int,
) -> ProcessResult:
    """Run one command and ensure timeout cleanup cannot wait forever."""
    options: dict[str, Any] = {
        "cwd": cwd,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True

    process = subprocess.Popen(command, **options)
    try:
        output, _ = process.communicate(timeout=timeout or None)
        return ProcessResult(output or "", process.returncode or 0)
    except subprocess.TimeoutExpired as error:
        terminate_process_tree(process)
        output = _drain_after_termination(process)
        partial = output or _text_output(error.output)
        return ProcessResult(partial, process.returncode or -1, timed_out=True)


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Best-effort termination of the command and descendants."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=TASKKILL_TIMEOUT_SECONDS,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass


def _drain_after_termination(process: subprocess.Popen[str]) -> str:
    """Collect remaining output without trusting descendants to close pipes."""
    try:
        output, _ = process.communicate(timeout=TERMINATION_GRACE_SECONDS)
        return output or ""
    except subprocess.TimeoutExpired:
        if process.stdout is not None:
            try:
                process.stdout.close()
            except OSError:
                pass
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        return ""


def _text_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
