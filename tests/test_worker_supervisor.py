from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import sys

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
    assert calls[2][1][supervisor_module.WORKER_ENV] == "1"



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
    monkeypatch.setenv(supervisor_module.WORKER_ENV, "1")
    assert supervisor_module.supervise_cli(
        ["--anything"],
        worker_script="runner.py",
        request_factory=lambda argv: None,
        worker_entry=lambda argv: 7,
    ) == 7


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
