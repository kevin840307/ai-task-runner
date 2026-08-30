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

from ..config.defaults import DEFAULT_WATCHDOG_INTERVAL, MAX_PROCESS_OUTPUT_CHARS
from ..utils.text import bounded_text


TERMINATION_GRACE_SECONDS = 5
TASKKILL_TIMEOUT_SECONDS = 10
ACTIVE_PROCESS_FILE = "active-process"
PROCESS_POLL_INTERVAL = 0.2
OUTPUT_QUEUE_CHUNKS = 256
OUTPUT_READ_CHARS = 4096
WORK_DIR_ENV = "AI_TASK_RUNNER_WORK_DIR"


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
    environment_overrides: dict[str, str] | None = None,
) -> ProcessResult:
    """Run one command and ensure timeout cleanup cannot wait forever."""
    environment = dict(os.environ)
    try:
        from ..bootstrap import current_runtime
        runtime = current_runtime()
        hooks = runtime.hooks
        watchdog_interval = runtime.config.watchdog_interval
        environment[WORK_DIR_ENV] = str(runtime.work)
        environment = hooks.process_environment(environment)
        command = hooks.process_command(command, environment)
    except RuntimeError:
        command = list(command)
        watchdog_interval = DEFAULT_WATCHDOG_INTERVAL
    if environment_overrides:
        environment.update(environment_overrides)
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

    process = subprocess.Popen(command, **options)
    _active_process(process, True)
    _process_event("runner.process.start", process, command, cwd)
    try:
        return _communicate_bounded(
            process,
            timeout,
            input_text,
            idle_timeout_after_change=idle_timeout_after_change,
            change_detected=change_detected,
            watchdog_interval=watchdog_interval,
        )
    finally:
        if process.poll() is None:
            terminate_process_tree(process)
        _process_event("runner.process.exit", process, command, cwd)
        _active_process(process, False)


def _active_process(process: subprocess.Popen[str], active: bool) -> None:
    try:
        from ..bootstrap import current_runtime
        path = current_runtime().work / ACTIVE_PROCESS_FILE
        value = f"{os.getpid()} {process.pid}"
        if active:
            path.write_text(value, encoding="ascii")
        elif path.read_text(encoding="ascii").strip() == value:
            path.unlink(missing_ok=True)
    except (RuntimeError, OSError):
        pass


def _process_event(kind: str, process: subprocess.Popen[str], command: Sequence[str], cwd: Path) -> None:
    try:
        from ..bootstrap import current_runtime
        current_runtime().events.publish({
            "type": kind,
            "pid": process.pid,
            "return_code": process.poll(),
            "command": Path(str(command[0])).name if command else "",
            "cwd": str(cwd),
        })
    except (RuntimeError, OSError):
        pass


def _communicate_with_watchdog(
    process: subprocess.Popen[str],
    timeout: int,
    idle_timeout_after_change: float,
    change_detected: Callable[[], bool],
    input_text: str | None,
    watchdog_interval: float,
) -> ProcessResult:
    """Compatibility wrapper around the shared bounded process collector."""
    return _communicate_bounded(
        process,
        timeout,
        input_text,
        idle_timeout_after_change=idle_timeout_after_change,
        change_detected=change_detected,
        watchdog_interval=watchdog_interval,
    )


def _communicate_bounded(
    process: subprocess.Popen[str],
    timeout: int,
    input_text: str | None,
    *,
    idle_timeout_after_change: float = 0,
    change_detected: Callable[[], bool] | None = None,
    watchdog_interval: float = DEFAULT_WATCHDOG_INTERVAL,
) -> ProcessResult:
    """Collect stdout through one bounded streaming path with optional idle watchdog."""
    deadline = time.monotonic() + timeout if timeout else None
    last_activity_at = time.monotonic()
    next_watchdog_at = last_activity_at
    partial = ""
    output_queue: queue.Queue[str] = queue.Queue(maxsize=OUTPUT_QUEUE_CHUNKS)

    if process.stdout is None:
        output, _ = process.communicate(input=input_text, timeout=timeout or None)
        return ProcessResult(
            bounded_text(output or "", MAX_PROCESS_OUTPUT_CHARS),
            process.returncode or 0,
        )

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
    watchdog_enabled = idle_timeout_after_change > 0 and change_detected is not None

    while True:
        now = time.monotonic()
        output, had_output = _drain_output(output_queue)
        partial = bounded_text(partial + output, MAX_PROCESS_OUTPUT_CHARS)

        if watchdog_enabled:
            changed = False
            if now >= next_watchdog_at:
                changed = _safe_change_detected(change_detected)
                next_watchdog_at = now + watchdog_interval
            if changed or had_output:
                last_activity_at = now

        if process.poll() is not None:
            partial = _finish_reader(reader, output_queue, partial)
            return ProcessResult(partial, process.returncode or 0)

        if deadline is not None and now >= deadline:
            terminate_process_tree(process)
            partial = _finish_reader(reader, output_queue, partial)
            return ProcessResult(
                partial,
                process.returncode or -1,
                timed_out=True,
            )

        if watchdog_enabled and now - last_activity_at >= idle_timeout_after_change:
            terminate_process_tree(process)
            partial = _finish_reader(reader, output_queue, partial)
            return ProcessResult(
                partial,
                process.returncode or -1,
                timed_out=True,
                idle_timed_out=True,
            )

        time.sleep(_next_stream_poll_timeout(
            now,
            deadline,
            last_activity_at if watchdog_enabled else None,
            idle_timeout_after_change if watchdog_enabled else 0,
        ))


def _finish_reader(
    reader: threading.Thread,
    output_queue: queue.Queue[str],
    partial: str,
) -> str:
    deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
    while reader.is_alive() and time.monotonic() < deadline:
        partial = bounded_text(
            partial + _drain_output(output_queue)[0],
            MAX_PROCESS_OUTPUT_CHARS,
        )
        reader.join(timeout=0.01)
    return bounded_text(
        partial + _drain_output(output_queue)[0],
        MAX_PROCESS_OUTPUT_CHARS,
    )


def _next_stream_poll_timeout(
    now: float,
    deadline: float | None,
    last_activity_at: float | None,
    idle_timeout_after_change: float,
) -> float:
    timeout = PROCESS_POLL_INTERVAL
    if deadline is not None:
        timeout = min(timeout, max(0.01, deadline - now))
    if last_activity_at is not None:
        idle_deadline = last_activity_at + idle_timeout_after_change
        timeout = min(timeout, max(0.01, idle_deadline - now))
    return timeout


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
        while chunk := pipe.read(OUTPUT_READ_CHARS):
            output_queue.put(chunk)
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


def _safe_change_detected(change_detected: Callable[[], bool]) -> bool:
    try:
        return change_detected()
    except OSError:
        return False


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
