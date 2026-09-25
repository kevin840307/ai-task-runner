from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import sys
import subprocess

import pytest

from runner.runtime import process_runner as process_module
from runner.runtime import supervisor as supervisor_module


def _request(root: Path):
    return SimpleNamespace(
        project_root=str(root),
        work_dir=".ai-task-runner",
        retry_delay=0,
        json_events=False,
    )


class FakeWorker:
    def __init__(self, code: int, pid: int):
        self.code = code
        self.pid = pid
        self.terminated = False

    def wait(self):
        return self.code

    def terminate(self):
        self.terminated = True


def test_supervisor_resumes_after_abnormal_worker_exit(tmp_path, monkeypatch):
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    state = work / "state.json"
    state.write_text("{}", encoding="utf-8")
    request = _request(tmp_path)
    workers = iter([FakeWorker(3221225477, 101), FakeWorker(0, 102)])
    calls = []

    def fake_popen(command, env):
        worker = next(workers)
        calls.append((command, env.copy(), worker.pid))
        return worker

    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(supervisor_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        supervisor_module,
        "cleanup_orphans",
        lambda states, pid: calls.append(("cleanup", tuple(states), pid)),
    )
    monkeypatch.setattr(supervisor_module, "_report_retry", lambda *args: None)

    result = supervisor_module.supervise_cli(
        [],
        worker_script="runner.py",
        request_factory=lambda argv: request,
        worker_entry=lambda argv: 0,
        state_locator=lambda current: [state],
    )
    assert result == 0
    assert "--resume" not in calls[0][0]
    assert ("cleanup", (state,), 101) in calls
    assert "--resume" in calls[2][0]
    assert calls[2][1][supervisor_module.WORKER_ENV] == str(os.getpid())



def test_supervisor_keyboard_interrupt_cleans_owned_children(tmp_path, monkeypatch):
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    state = work / "state.json"
    state.write_text("{}", encoding="utf-8")
    request = _request(tmp_path)
    calls = []

    class InterruptedWorker(FakeWorker):
        def wait(self):
            raise KeyboardInterrupt()

    worker = InterruptedWorker(0, 101)
    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(supervisor_module.subprocess, "Popen", lambda command, env: worker)
    monkeypatch.setattr(
        supervisor_module,
        "cleanup_orphans",
        lambda states, pid: calls.append((tuple(states), pid)),
    )

    result = supervisor_module.supervise_cli(
        [],
        worker_script="runner.py",
        request_factory=lambda argv: request,
        worker_entry=lambda argv: 0,
        state_locator=lambda current: [state],
    )

    assert result == 130
    assert worker.terminated is True
    assert calls == [((state,), 101)]

def test_supervisor_does_not_restart_without_saved_state(tmp_path, monkeypatch):
    request = _request(tmp_path)
    calls = []
    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(
        supervisor_module.subprocess,
        "Popen",
        lambda command, env: calls.append(command) or FakeWorker(9, 101),
    )
    monkeypatch.setattr(
        supervisor_module,
        "cleanup_orphans",
        lambda states, pid: calls.append(("cleanup", tuple(states), pid)),
    )
    result = supervisor_module.supervise_cli(
        [],
        worker_script="runner.py",
        request_factory=lambda argv: request,
        worker_entry=lambda argv: 0,
        state_locator=lambda current: [],
    )
    assert result == 9
    assert calls[0][0] == sys.executable
    assert calls[1] == ("cleanup", (), 101)


def test_worker_mode_calls_entry_directly(monkeypatch):
    monkeypatch.setenv(supervisor_module.WORKER_ENV, str(os.getppid()))
    assert supervisor_module.supervise_cli(
        ["--anything"],
        worker_script="runner.py",
        request_factory=lambda argv: None,
        worker_entry=lambda argv: 7,
    ) == 7


def test_inherited_worker_mode_blocks_nested_runner(monkeypatch, capsys):
    monkeypatch.setenv(supervisor_module.WORKER_ENV, "1")
    called = []

    assert supervisor_module.supervise_cli(
        [],
        worker_script="runner.py",
        request_factory=lambda argv: called.append("request"),
        worker_entry=lambda argv: called.append("worker") or 0,
    ) == 2

    assert called == []
    assert "nested AI Task Runner launch blocked" in capsys.readouterr().err


def test_run_process_logs_pid_return_code_and_clears_active_file(tmp_path, monkeypatch):
    events = []
    work = tmp_path / ".ai-task-runner"
    work.mkdir()

    class Hooks:
        def process_environment(self, env):
            return env

        def process_command(self, command, env):
            return list(command)

    runtime = SimpleNamespace(
        work=work,
        hooks=Hooks(),
        config=SimpleNamespace(watchdog_interval=0.01),
        events=SimpleNamespace(publish=events.append),
    )
    import runner.bootstrap as bootstrap
    monkeypatch.setattr(bootstrap, "current_runtime", lambda: runtime)

    result = process_module.run_process(
        [sys.executable, "-c", "import os; print(os.environ['AI_TASK_RUNNER_WORK_DIR'])"],
        tmp_path,
        10,
    )

    assert result.return_code == 0
    assert result.output.strip() == str(work)
    assert [event["type"] for event in events] == ["runner.process.start", "runner.process.exit"]
    assert events[0]["pid"] > 0
    assert events[0]["return_code"] is None
    assert events[1]["pid"] == events[0]["pid"]
    assert events[1]["return_code"] == 0
    assert not (work / process_module.ACTIVE_PROCESS_FILE).exists()
    assert (work / process_module.STREAM_FILE).read_text(encoding="utf-8").strip() == str(work)


def test_cleanup_orphans_use_each_state_work_directory(tmp_path, monkeypatch):
    first_work = tmp_path / ".ai-task-runner" / "script" / "001"
    second_work = tmp_path / ".ai-task-runner" / "script" / "002"
    first_work.mkdir(parents=True)
    second_work.mkdir(parents=True)
    first_state = first_work / "state.json"
    second_state = second_work / "state.json"
    first_state.write_text("{}", encoding="utf-8")
    second_state.write_text("{}", encoding="utf-8")
    first_active = first_work / "active-process"
    second_active = second_work / "active-process"
    first_active.write_text("100 200", encoding="ascii")
    second_active.write_text("999 300", encoding="ascii")
    calls = []
    if os.name == "nt":
        monkeypatch.setattr(
            supervisor_module.subprocess,
            "run",
            lambda command, **kwargs: calls.append(command),
        )
    else:
        monkeypatch.setattr(
            supervisor_module.os,
            "killpg",
            lambda pid, sig: calls.append((pid, sig)),
        )

    supervisor_module.cleanup_orphans([first_state, second_state], 100)
    assert calls
    child = calls[0][2] if os.name == "nt" else calls[0][0]
    assert str(child) == "200"
    assert not first_active.exists()
    assert second_active.exists()


def test_supervisor_writes_and_removes_runtime_process_marker(tmp_path, monkeypatch):
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    request = _request(tmp_path)
    worker = FakeWorker(0, 4242)
    seen = {}

    def fake_popen(command, env):
        return worker

    original_wait = worker.wait

    def wait_and_capture():
        marker = work / supervisor_module.RUNNER_PROCESS_FILE
        assert marker.is_file()
        import json
        seen.update(json.loads(marker.read_text(encoding="utf-8")))
        return original_wait()

    worker.wait = wait_and_capture
    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(supervisor_module.subprocess, "Popen", fake_popen)

    result = supervisor_module.supervise_cli(
        [],
        worker_script="runner.py",
        request_factory=lambda argv: request,
        worker_entry=lambda argv: 0,
        state_locator=lambda current: [],
    )

    assert result == 0
    assert seen["schema_version"] == 1
    assert seen["supervisor_pid"] == os.getpid()
    assert seen["worker_pid"] == 4242
    assert seen["project_root"] == str(tmp_path.resolve())
    assert seen["work_dir"] == ".ai-task-runner"
    assert seen["started_at"] > 0
    assert not (work / supervisor_module.RUNNER_PROCESS_FILE).exists()


def test_supervisor_runtime_marker_tracks_restarted_worker(tmp_path, monkeypatch):
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    state = work / "state.json"
    state.write_text("{}", encoding="utf-8")
    request = _request(tmp_path)
    workers = iter([FakeWorker(9, 101), FakeWorker(0, 202)])
    seen = []

    def fake_popen(command, env):
        worker = next(workers)
        original_wait = worker.wait

        def wait_and_capture():
            import json
            marker = work / supervisor_module.RUNNER_PROCESS_FILE
            seen.append(json.loads(marker.read_text(encoding="utf-8"))["worker_pid"])
            return original_wait()

        worker.wait = wait_and_capture
        return worker

    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(supervisor_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(supervisor_module, "cleanup_orphans", lambda *args: None)
    monkeypatch.setattr(supervisor_module, "_report_retry", lambda *args: None)

    result = supervisor_module.supervise_cli(
        [],
        worker_script="runner.py",
        request_factory=lambda argv: request,
        worker_entry=lambda argv: 0,
        state_locator=lambda current: [state],
    )

    assert result == 0
    assert seen == [101, 202]
    assert not (work / supervisor_module.RUNNER_PROCESS_FILE).exists()


def test_supervisor_stop_request_terminates_worker_and_cleans_children(tmp_path, monkeypatch):
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    state = work / "state.json"
    state.write_text("{}", encoding="utf-8")
    request = _request(tmp_path)
    stop_request = work / supervisor_module.STOP_REQUEST_FILE
    calls = []

    class RunningWorker(FakeWorker):
        def __init__(self):
            super().__init__(0, 31337)
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            if self.poll_count == 1:
                stop_request.write_text("stop\n", encoding="utf-8")
            return None

    worker = RunningWorker()
    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(supervisor_module.subprocess, "Popen", lambda command, env: worker)
    monkeypatch.setattr(supervisor_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        supervisor_module,
        "cleanup_orphans",
        lambda states, pid: calls.append((tuple(states), pid)),
    )

    result = supervisor_module.supervise_cli(
        [],
        worker_script="runner.py",
        request_factory=lambda argv: request,
        worker_entry=lambda argv: 0,
        state_locator=lambda current: [state],
    )

    assert result == 130
    assert worker.terminated is True
    assert calls == [((state,), 31337)]
    assert not stop_request.exists()
    assert not (work / supervisor_module.RUNNER_PROCESS_FILE).exists()


def test_supervisor_clears_stale_stop_request_before_new_run(tmp_path, monkeypatch):
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    stop_request = work / supervisor_module.STOP_REQUEST_FILE
    stop_request.write_text("stale\n", encoding="utf-8")
    request = _request(tmp_path)
    worker = FakeWorker(0, 77)

    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(supervisor_module.subprocess, "Popen", lambda command, env: worker)

    result = supervisor_module.supervise_cli(
        [],
        worker_script="runner.py",
        request_factory=lambda argv: request,
        worker_entry=lambda argv: 0,
        state_locator=lambda current: [],
    )

    assert result == 0
    assert not stop_request.exists()



def test_supervisor_rejects_duplicate_project_work_dir_owner(tmp_path, monkeypatch, capsys):
    request = _request(tmp_path)
    lock = tmp_path / ".ai-task-runner" / supervisor_module.RUN_LOCK_FILE
    token = supervisor_module._acquire_run_lock(lock)
    popen_calls = []
    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(
        supervisor_module.subprocess,
        "Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)),
    )
    try:
        result = supervisor_module.supervise_cli(
            [],
            worker_script="runner.py",
            request_factory=lambda argv: request,
            worker_entry=lambda argv: 0,
            state_locator=lambda current: [],
        )
    finally:
        supervisor_module._release_run_lock(lock, token)

    assert result == 2
    assert popen_calls == []
    assert "already owns this project/work_dir" in capsys.readouterr().err


def test_supervisor_reclaims_stale_project_work_dir_lock(tmp_path, monkeypatch):
    request = _request(tmp_path)
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    lock = work / supervisor_module.RUN_LOCK_FILE
    lock.write_text(
        '{"schema_version":1,"pid":99999999,"token":"dead","started_at":1}',
        encoding="utf-8",
    )
    worker = FakeWorker(0, 202)
    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(supervisor_module, "_owner_pid_alive", lambda pid: False)
    monkeypatch.setattr(supervisor_module.subprocess, "Popen", lambda command, env: worker)

    result = supervisor_module.supervise_cli(
        [],
        worker_script="runner.py",
        request_factory=lambda argv: request,
        worker_entry=lambda argv: 0,
        state_locator=lambda current: [],
    )

    assert result == 0
    assert not lock.exists()


def test_windows_orphan_taskkill_has_timeout_and_timeout_is_fail_safe(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 0))

    monkeypatch.setattr(supervisor_module.subprocess, "run", fake_run)

    with pytest.raises(subprocess.TimeoutExpired):
        supervisor_module._windows_taskkill_tree(202)

    assert calls
    assert calls[0][0] == ["taskkill", "/PID", "202", "/T", "/F"]
    assert calls[0][1]["timeout"] == supervisor_module.TASKKILL_TIMEOUT_SECONDS


def test_terminate_worker_waits_then_kills_stubborn_process():
    calls = []

    class StubbornWorker:
        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            if len([item for item in calls if isinstance(item, tuple) and item[0] == "wait"]) == 1:
                raise subprocess.TimeoutExpired("worker", timeout)
            return 0

        def kill(self):
            calls.append("kill")

    supervisor_module._terminate_worker(StubbornWorker(), timeout=0.1)

    assert calls == [
        "terminate",
        ("wait", 0.1),
        "kill",
        ("wait", 0.1),
    ]


def test_supervisor_initial_marker_failure_releases_run_lock(tmp_path, monkeypatch):
    request = _request(tmp_path)
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    lock = work / supervisor_module.RUN_LOCK_FILE
    popen_calls = []

    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(
        supervisor_module,
        "_write_runtime_marker",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    monkeypatch.setattr(
        supervisor_module.subprocess,
        "Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)),
    )

    with pytest.raises(OSError, match="disk unavailable"):
        supervisor_module.supervise_cli(
            [],
            worker_script="runner.py",
            request_factory=lambda argv: request,
            worker_entry=lambda argv: 0,
            state_locator=lambda current: [],
        )

    assert popen_calls == []
    assert not lock.exists()


def test_supervisor_worker_marker_failure_terminates_worker_before_unlock(tmp_path, monkeypatch):
    request = _request(tmp_path)
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    lock = work / supervisor_module.RUN_LOCK_FILE
    worker = FakeWorker(0, 5150)
    cleanup = []
    writes = []

    def fake_marker(path, request, started_at, *, worker_pid):
        writes.append(worker_pid)
        if worker_pid is not None:
            raise OSError("marker update failed")

    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(supervisor_module, "_write_runtime_marker", fake_marker)
    monkeypatch.setattr(supervisor_module.subprocess, "Popen", lambda *args, **kwargs: worker)
    monkeypatch.setattr(
        supervisor_module,
        "cleanup_orphans",
        lambda states, pid: cleanup.append((tuple(states), pid)),
    )

    with pytest.raises(OSError, match="marker update failed"):
        supervisor_module.supervise_cli(
            [],
            worker_script="runner.py",
            request_factory=lambda argv: request,
            worker_entry=lambda argv: 0,
            state_locator=lambda current: [],
        )

    assert writes == [None, 5150]
    assert worker.terminated is True
    assert cleanup == [((), 5150)]
    assert not lock.exists()


def test_supervisor_stops_restarting_after_same_state_crashes_three_times(tmp_path, monkeypatch):
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    state = work / "state.json"
    state.write_text(
        '{"run_id":"same","stage":"executing","current":0,"cycle":1,'
        '"completed":false,"tasks":[{"id":"t1","status":"pending","attempts":1}]}',
        encoding="utf-8",
    )
    request = _request(tmp_path)
    workers = iter([
        FakeWorker(9, 101),
        FakeWorker(9, 102),
        FakeWorker(9, 103),
    ])
    calls = []

    monkeypatch.delenv(supervisor_module.WORKER_ENV, raising=False)
    monkeypatch.setattr(
        supervisor_module.subprocess,
        "Popen",
        lambda command, env: calls.append(command) or next(workers),
    )
    monkeypatch.setattr(supervisor_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(supervisor_module, "cleanup_orphans", lambda *args: None)
    monkeypatch.setattr(supervisor_module, "_report_retry", lambda *args: None)

    result = supervisor_module.supervise_cli(
        [],
        worker_script="runner.py",
        request_factory=lambda argv: request,
        worker_entry=lambda argv: 0,
        state_locator=lambda current: [state],
    )

    assert result == 9
    assert len(calls) == 3


def test_clear_stop_request_can_fail_closed(monkeypatch, tmp_path):
    path = tmp_path / "stop.request"

    class LockedPath:
        def unlink(self, missing_ok=False):
            raise PermissionError("locked")

    monkeypatch.setattr(supervisor_module, "io_path", lambda value: LockedPath())
    monkeypatch.setattr(supervisor_module.time, "sleep", lambda _: None)

    supervisor_module._clear_stop_request(path)
    with pytest.raises(PermissionError, match="locked"):
        supervisor_module._clear_stop_request(path, strict=True)


def test_runtime_marker_retries_transient_permission_error(tmp_path, monkeypatch):
    marker = tmp_path / "runner-process.json"
    request = _request(tmp_path)
    original_replace = supervisor_module.os.replace
    calls = []

    def flaky_replace(source, target):
        calls.append((source, target))
        if len(calls) < 3:
            raise PermissionError("busy")
        return original_replace(source, target)

    monkeypatch.setattr(supervisor_module.os, "replace", flaky_replace)
    monkeypatch.setattr(supervisor_module.time, "sleep", lambda _: None)

    supervisor_module._write_runtime_marker(
        marker,
        request,
        123.0,
        worker_pid=456,
    )

    assert len(calls) == 3
    payload = __import__("json").loads(marker.read_text(encoding="utf-8"))
    assert payload["worker_pid"] == 456
    assert payload["started_at"] == 123.0
