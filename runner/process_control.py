"""Cross-platform subprocess timeout and process-tree cleanup helpers."""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .safety.git_guard import guarded_command, guarded_environment

TERMINATION_GRACE_SECONDS = 5
TASKKILL_TIMEOUT_SECONDS = 10
WATCHDOG_POLL_SECONDS = 1.0


@dataclass(frozen=True)
class ProcessResult:
    output: str
    return_code: int
    timed_out: bool = False
    idle_timed_out: bool = False


def run_process(
    command: Sequence[str],
    cwd: Path,
    timeout: int,
    idle_timeout_after_change: float = 0,
    change_detected: Callable[[], bool] | None = None,
    input_text: str | None = None,
) -> ProcessResult:
    """Run one command and ensure timeout cleanup cannot wait forever."""
    environment = guarded_environment()
    options: dict[str, Any] = {
        "cwd": cwd,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "stdin": subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "env": environment,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True

    process = subprocess.Popen(guarded_command(command, environment), **options)
    try:
        if idle_timeout_after_change and change_detected is not None:
            return _communicate_with_watchdog(
                process,
                timeout,
                idle_timeout_after_change,
                change_detected,
                input_text,
            )

        try:
            output, _ = process.communicate(input=input_text, timeout=timeout or None)
            return ProcessResult(output or "", process.returncode or 0)
        except subprocess.TimeoutExpired as error:
            terminate_process_tree(process)
            output = _drain_after_termination(process)
            partial = output or _text_output(error.output)
            return ProcessResult(partial, process.returncode or -1, timed_out=True)
    finally:
        if process.poll() is None:
            terminate_process_tree(process)


def _communicate_with_watchdog(
    process: subprocess.Popen[str],
    timeout: int,
    idle_timeout_after_change: float,
    change_detected: Callable[[], bool],
    input_text: str | None,
) -> ProcessResult:
    deadline = time.monotonic() + timeout if timeout else None
    last_activity_at: float = time.monotonic()
    partial = ""
    output_queue: queue.Queue[str] = queue.Queue()

    if process.stdout is None:
        output, _ = process.communicate(input=input_text, timeout=timeout or None)
        return ProcessResult(output or "", process.returncode or 0)

    if input_text is not None:
        threading.Thread(
            target=_send_input,
            args=(process, input_text),
            daemon=True,
        ).start()

    reader = threading.Thread(
        target=_read_stdout,
        args=(process.stdout, output_queue),
        daemon=True,
    )
    reader.start()

    while True:
        now = time.monotonic()
        output, had_output = _drain_output(output_queue)
        partial += output
        if _safe_change_detected(change_detected) or had_output:
            last_activity_at = now

        if process.poll() is not None:
            reader.join(timeout=0.2)
            partial += _drain_output(output_queue)[0]
            return ProcessResult(partial, process.returncode or 0)

        if deadline is not None and now >= deadline:
            return _terminate_timeout(process, partial, idle=False)
        if now - last_activity_at >= idle_timeout_after_change:
            return _terminate_timeout(process, partial, idle=True)

        time.sleep(
            _next_poll_timeout(
                now,
                deadline,
                last_activity_at,
                idle_timeout_after_change,
            )
        )



def _send_input(process: subprocess.Popen[str], input_text: str) -> None:
    """Write one complete stdin payload and close it so the child receives EOF."""
    pipe = process.stdin
    if pipe is None:
        return
    try:
        pipe.write(input_text)
        pipe.flush()
    except OSError:
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass
        process.stdin = None

def _read_stdout(pipe: Any, output_queue: queue.Queue[str]) -> None:
    try:
        for line in iter(pipe.readline, ""):
            if line:
                output_queue.put(line)
    except OSError:
        pass


def _drain_output(output_queue: queue.Queue[str]) -> tuple[str, bool]:
    chunks: list[str] = []
    while True:
        try:
            chunks.append(output_queue.get_nowait())
        except queue.Empty:
            break
    return "".join(chunks), bool(chunks)


def _next_poll_timeout(
    now: float,
    deadline: float | None,
    last_activity_at: float,
    idle_timeout_after_change: float,
) -> float:
    timeout = WATCHDOG_POLL_SECONDS
    if deadline is not None:
        timeout = min(timeout, max(0.01, deadline - now))
    idle_deadline = last_activity_at + idle_timeout_after_change
    timeout = min(timeout, max(0.01, idle_deadline - now))
    return timeout


def _safe_change_detected(change_detected: Callable[[], bool]) -> bool:
    try:
        return change_detected()
    except OSError:
        return False


def _terminate_timeout(
    process: subprocess.Popen[str],
    partial: str,
    idle: bool,
) -> ProcessResult:
    terminate_process_tree(process)
    output = _drain_after_termination(process) or partial
    return ProcessResult(
        output,
        process.returncode or -1,
        timed_out=True,
        idle_timed_out=idle,
    )


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
