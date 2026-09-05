"""Process-level crash isolation for long-running CLI/host workers."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .events import retry_event
from .process_runner import ACTIVE_PROCESS_FILE
from ..utils.files import atomic_write_text

WORKER_ENV = "AI_TASK_RUNNER_WORKER"
RUNNER_PROCESS_FILE = "runner-process.json"
STOP_REQUEST_FILE = "stop.request"
CONTROL_POLL_INTERVAL = 0.2
RequestFactory = Callable[[Sequence[str]], Any]
WorkerEntry = Callable[[Sequence[str]], int]
StateLocator = Callable[[Any], Sequence[str | Path]]


def supervise_cli(
    argv: Sequence[str],
    *,
    worker_script: str | Path,
    request_factory: RequestFactory,
    worker_entry: WorkerEntry,
    state_locator: StateLocator | None = None,
) -> int:
    """Keep a worker process isolated and resume persisted state after hard exits."""
    if os.environ.get(WORKER_ENV) == "1":
        return worker_entry(argv)

    request = request_factory(argv)
    states = (
        [Path(path) for path in state_locator(request)]
        if state_locator is not None
        else [Path(request.project_root, request.work_dir, "state.json").resolve()]
    )
    worker_args = list(argv)
    runtime_marker = Path(request.project_root, request.work_dir, RUNNER_PROCESS_FILE).resolve()
    started_at = time.time()
    stop_request = runtime_marker.with_name(STOP_REQUEST_FILE)
    _clear_stop_request(stop_request)
    _write_runtime_marker(runtime_marker, request, started_at, worker_pid=None)
    try:
        return _supervise_workers(
            request,
            worker_args,
            worker_script=worker_script,
            states=states,
            runtime_marker=runtime_marker,
            started_at=started_at,
            stop_request=stop_request,
        )
    finally:
        _remove_runtime_marker(runtime_marker)


def _supervise_workers(
    request: Any,
    worker_args: list[str],
    *,
    worker_script: str | Path,
    states: Sequence[Path],
    runtime_marker: Path,
    started_at: float,
    stop_request: Path,
) -> int:
    while True:
        env = dict(os.environ)
        env[WORKER_ENV] = "1"
        worker = subprocess.Popen(
            [sys.executable, str(Path(worker_script).resolve()), *worker_args],
            env=env,
        )
        _write_runtime_marker(runtime_marker, request, started_at, worker_pid=worker.pid)
        try:
            code = _wait_for_worker(worker, stop_request)
        except _StopRequested:
            worker.terminate()
            cleanup_orphans(states, worker.pid)
            _clear_stop_request(stop_request)
            return 130
        except KeyboardInterrupt:
            worker.terminate()
            cleanup_orphans(states, worker.pid)
            return 130
        if code in (0, 1, 130):
            return code
        cleanup_orphans(states, worker.pid)
        if not any(path.is_file() for path in states):
            return code
        _report_retry(
            request,
            f"worker exited unexpectedly ({code}); resuming saved state",
        )
        worker_args = [
            arg for arg in worker_args if arg not in {"--resume", "--force-new"}
        ] + ["--resume"]
        if _sleep_until_retry(max(1, request.retry_delay), stop_request):
            _clear_stop_request(stop_request)
            return 130



class _StopRequested(Exception):
    pass


def _wait_for_worker(worker: Any, stop_request: Path) -> int:
    """Wait for one worker while allowing a detached UI to request a safe stop."""
    poll = getattr(worker, "poll", None)
    if poll is None:
        return int(worker.wait())
    while True:
        code = poll()
        if code is not None:
            return int(code)
        if stop_request.is_file():
            raise _StopRequested
        time.sleep(CONTROL_POLL_INTERVAL)


def _sleep_until_retry(seconds: float, stop_request: Path) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if stop_request.is_file():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(CONTROL_POLL_INTERVAL, remaining))


def _clear_stop_request(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

def _write_runtime_marker(
    path: Path,
    request: Any,
    started_at: float,
    *,
    worker_pid: int | None,
) -> None:
    payload = {
        "schema_version": 1,
        "supervisor_pid": os.getpid(),
        "worker_pid": worker_pid,
        "started_at": started_at,
        "project_root": str(Path(request.project_root).resolve()),
        "work_dir": str(request.work_dir),
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _remove_runtime_marker(path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("supervisor_pid", -1)) == os.getpid():
            path.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass


def cleanup_orphans(state_files: Sequence[str | Path], worker_pid: int) -> None:
    """Kill active children owned by one crashed worker across Direct/YAML runs."""
    work_dirs = {Path(path).resolve().parent for path in state_files}
    for work in work_dirs:
        _cleanup_orphan_marker(work / ACTIVE_PROCESS_FILE, worker_pid)


def _cleanup_orphan_marker(path: Path, worker_pid: int) -> None:
    try:
        owner, child = map(int, path.read_text(encoding="ascii").split())
        if owner != worker_pid:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(child), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(child, signal.SIGKILL)
        path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def _report_retry(request: Any, message: str) -> None:
    if request.json_events:
        print(json.dumps(retry_event(message, exit_code=0)), flush=True)
    else:
        print(f"ERROR: {message}", file=sys.stderr)


__all__ = ["RUNNER_PROCESS_FILE", "STOP_REQUEST_FILE", "WORKER_ENV", "cleanup_orphans", "supervise_cli"]
