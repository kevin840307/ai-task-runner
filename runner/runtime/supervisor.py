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

WORKER_ENV = "AI_TASK_RUNNER_WORKER"
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
    while True:
        env = dict(os.environ)
        env[WORKER_ENV] = "1"
        worker = subprocess.Popen(
            [sys.executable, str(Path(worker_script).resolve()), *worker_args],
            env=env,
        )
        try:
            code = worker.wait()
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
        time.sleep(max(1, request.retry_delay))


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


__all__ = ["WORKER_ENV", "cleanup_orphans", "supervise_cli"]
