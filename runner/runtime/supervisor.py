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

from ..utils.files import io_path
from typing import Any

from .events import retry_event
from .process_runner import ACTIVE_PROCESS_FILE

WORKER_ENV = "AI_TASK_RUNNER_WORKER"
RUNNER_PROCESS_FILE = "runner-process.json"
RUN_LOCK_FILE = "run.lock"
STOP_REQUEST_FILE = "stop.request"
CONTROL_POLL_INTERVAL = 0.2
RUN_LOCK_STALE_GRACE_SECONDS = 5.0
TASKKILL_TIMEOUT_SECONDS = 10
CONTROL_FILE_RETRIES = 10
CONTROL_FILE_RETRY_DELAY = 0.05
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
    worker_parent = os.environ.get(WORKER_ENV)
    if worker_parent:
        if worker_parent == str(os.getppid()):
            return worker_entry(argv)
        print("ERROR: nested AI Task Runner launch blocked", file=sys.stderr)
        return 2

    request = request_factory(argv)
    states = (
        [Path(path) for path in state_locator(request)]
        if state_locator is not None
        else [Path(request.project_root, request.work_dir, "state.json").resolve()]
    )
    worker_args = list(argv)
    runtime_marker = Path(request.project_root, request.work_dir, RUNNER_PROCESS_FILE).resolve()
    run_lock = runtime_marker.with_name(RUN_LOCK_FILE)
    try:
        lock_token = _acquire_run_lock(run_lock)
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    started_at = time.time()
    stop_request = runtime_marker.with_name(STOP_REQUEST_FILE)
    try:
        _clear_stop_request(stop_request, strict=True)
        _write_runtime_marker(runtime_marker, request, started_at, worker_pid=None)
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
        _release_run_lock(run_lock, lock_token)


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
    crash_key = ""
    crash_repeats = 0
    while True:
        env = dict(os.environ)
        env[WORKER_ENV] = str(os.getpid())
        worker = subprocess.Popen(
            [sys.executable, str(Path(worker_script).resolve()), *worker_args],
            env=env,
        )
        try:
            _write_runtime_marker(runtime_marker, request, started_at, worker_pid=worker.pid)
        except OSError:
            _terminate_worker(worker)
            cleanup_orphans(states, worker.pid)
            raise
        try:
            code = _wait_for_worker(worker, stop_request)
        except _StopRequested:
            _terminate_worker(worker)
            cleanup_orphans(states, worker.pid)
            _clear_stop_request(stop_request)
            return 130
        except KeyboardInterrupt:
            _terminate_worker(worker)
            cleanup_orphans(states, worker.pid)
            return 130
        if code in (0, 1, 130):
            return code
        cleanup_orphans(states, worker.pid)
        if not any(path.is_file() for path in states):
            return code
        progress_key = _state_progress_fingerprint(states)
        crash_repeats = crash_repeats + 1 if progress_key == crash_key else 1
        crash_key = progress_key
        if crash_repeats >= 3:
            if request.json_events:
                print(json.dumps(retry_event(
                    "worker repeatedly exited without durable progress",
                    exit_code=code,
                )), flush=True)
            else:
                print(
                    "ERROR: worker repeatedly exited without durable progress",
                    file=sys.stderr,
                )
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


def _acquire_run_lock(path: Path) -> str:
    """Own one project_root + work_dir across CLI/UI launches and resumes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}-{time.time_ns()}"
    payload = json.dumps({
        "schema_version": 1,
        "pid": os.getpid(),
        "token": token,
        "started_at": time.time(),
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")
    for _ in range(2):
        try:
            fd = os.open(str(io_path(path)), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not _remove_stale_run_lock(path):
                raise RuntimeError(
                    f"another AI Task Runner already owns this project/work_dir: {path}"
                )
            continue
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        return token
    raise RuntimeError(
        f"another AI Task Runner already owns this project/work_dir: {path}"
    )


def _remove_stale_run_lock(path: Path) -> bool:
    try:
        stat = io_path(path).stat()
        raw = io_path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        pid = int(data.get("pid", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        try:
            age = time.time() - io_path(path).stat().st_mtime
        except OSError:
            return True
        if age < RUN_LOCK_STALE_GRACE_SECONDS:
            return False
        try:
            io_path(path).unlink(missing_ok=True)
            return True
        except OSError:
            return False
    if pid > 0 and _owner_pid_alive(pid):
        return False
    try:
        # Re-read before unlinking so a changed/replaced lock is never stolen.
        current = json.loads(io_path(path).read_text(encoding="utf-8"))
        if current.get("token") != data.get("token"):
            return False
        io_path(path).unlink(missing_ok=True)
        return True
    except (OSError, json.JSONDecodeError):
        return False


def _owner_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=3,
            )
            output = result.stdout.strip().lower()
            return bool(output and "no tasks are running" not in output and str(pid) in output)
        except (OSError, subprocess.SubprocessError):
            return True
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _release_run_lock(path: Path, token: str) -> None:
    try:
        data = json.loads(io_path(path).read_text(encoding="utf-8"))
        if data.get("token") == token:
            io_path(path).unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError):
        pass


def _clear_stop_request(path: Path, *, strict: bool = False) -> None:
    for attempt in range(CONTROL_FILE_RETRIES):
        try:
            io_path(path).unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt < CONTROL_FILE_RETRIES - 1:
                time.sleep(CONTROL_FILE_RETRY_DELAY * (attempt + 1))
                continue
            if strict:
                raise
            return
        except OSError:
            if strict:
                raise
            return

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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        for attempt in range(CONTROL_FILE_RETRIES):
            try:
                os.replace(io_path(temporary), io_path(path))
                return
            except PermissionError:
                if attempt == CONTROL_FILE_RETRIES - 1:
                    raise
                time.sleep(CONTROL_FILE_RETRY_DELAY * (attempt + 1))
    except OSError:
        try:
            io_path(temporary).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _remove_runtime_marker(path: Path) -> None:
    try:
        data = json.loads(io_path(path).read_text(encoding="utf-8"))
        if int(data.get("supervisor_pid", -1)) == os.getpid():
            io_path(path).unlink(missing_ok=True)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass


def cleanup_orphans(state_files: Sequence[str | Path], worker_pid: int) -> None:
    """Kill active children owned by one crashed worker across Direct/YAML runs."""
    work_dirs = {Path(path).resolve().parent for path in state_files}
    for work in work_dirs:
        _cleanup_orphan_marker(work / ACTIVE_PROCESS_FILE, worker_pid)


def _windows_taskkill_tree(child_pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(child_pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=TASKKILL_TIMEOUT_SECONDS,
    )


def _cleanup_orphan_marker(path: Path, worker_pid: int) -> None:
    try:
        owner, child = map(int, io_path(path).read_text(encoding="ascii").split())
        if owner != worker_pid:
            return
        if os.name == "nt":
            _windows_taskkill_tree(child)
        else:
            os.killpg(child, signal.SIGKILL)
        io_path(path).unlink(missing_ok=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def _state_progress_fingerprint(states: Sequence[Path]) -> str:
    summary: list[dict[str, Any]] = []
    for path in states:
        if not path.is_file():
            continue
        try:
            state = json.loads(io_path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summary.append({"path": str(path.resolve()), "unreadable": True})
            continue
        tasks = state.get("tasks") if isinstance(state, dict) and isinstance(state.get("tasks"), list) else []
        summary.append({
            "path": str(path.resolve()),
            "run_id": state.get("run_id") if isinstance(state, dict) else None,
            "stage": state.get("stage") if isinstance(state, dict) else None,
            "current": state.get("current") if isinstance(state, dict) else None,
            "cycle": state.get("cycle") if isinstance(state, dict) else None,
            "workflow_position": state.get("workflow_position") if isinstance(state, dict) else None,
            "task_step": state.get("task_step") if isinstance(state, dict) else None,
            "completed": state.get("completed") if isinstance(state, dict) else None,
            "tasks": [
                {
                    "id": task.get("id"),
                    "status": task.get("status"),
                    "attempts": task.get("attempts"),
                }
                for task in tasks
                if isinstance(task, dict)
            ],
        })
    return json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _terminate_worker(worker: Any, timeout: float = 5.0) -> None:
    """Bound worker shutdown before releasing the project/work_dir ownership lock."""
    try:
        worker.terminate()
    except OSError:
        pass
    wait = getattr(worker, "wait", None)
    if not callable(wait):
        return
    try:
        wait(timeout=timeout)
        return
    except TypeError:
        # Lightweight test doubles may not expose Popen.wait(timeout=...).
        try:
            wait()
            return
        except KeyboardInterrupt:
            pass
        except Exception:
            return
    except KeyboardInterrupt:
        pass
    except subprocess.TimeoutExpired:
        pass
    try:
        worker.kill()
    except (AttributeError, OSError):
        return
    try:
        wait(timeout=timeout)
    except (KeyboardInterrupt, TypeError, OSError, subprocess.SubprocessError):
        pass


def _report_retry(request: Any, message: str) -> None:
    if request.json_events:
        print(json.dumps(retry_event(message, exit_code=0)), flush=True)
    else:
        print(f"ERROR: {message}", file=sys.stderr)


__all__ = ["RUNNER_PROCESS_FILE", "RUN_LOCK_FILE", "STOP_REQUEST_FILE", "WORKER_ENV", "cleanup_orphans", "supervise_cli"]
