from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import ai_task_runner
from runner.runtime import process_runner as process_module


def _args(root: Path) -> list[str]:
    return [
        "--goal", "do work",
        "--project-root", str(root),
        "--validator", "ai",
        "--retry-delay", "0",
    ]


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
    (work / "state.json").write_text("{}", encoding="utf-8")
    workers = iter([FakeWorker(3221225477, 101), FakeWorker(0, 102)])
    calls = []

    def fake_popen(command, env):
        worker = next(workers)
        calls.append((command, env.copy(), worker.pid))
        return worker

    monkeypatch.delenv("AI_TASK_RUNNER_WORKER", raising=False)
    monkeypatch.setattr(ai_task_runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ai_task_runner.time, "sleep", lambda _: None)
    monkeypatch.setattr(ai_task_runner, "_report_error", lambda *args: None)
    monkeypatch.setattr(ai_task_runner, "_cleanup_orphan", lambda request, pid: calls.append(("cleanup", pid)))

    assert ai_task_runner._supervise(_args(tmp_path)) == 0
    assert "--resume" not in calls[0][0]
    assert ("cleanup", 101) in calls
    assert "--resume" in calls[2][0]
    assert calls[2][1]["AI_TASK_RUNNER_WORKER"] == "1"


def test_supervisor_does_not_restart_without_saved_state(tmp_path, monkeypatch):
    calls = []
    monkeypatch.delenv("AI_TASK_RUNNER_WORKER", raising=False)
    monkeypatch.setattr(
        ai_task_runner.subprocess,
        "Popen",
        lambda command, env: calls.append(command) or FakeWorker(9, 101),
    )
    assert ai_task_runner._supervise(_args(tmp_path)) == 9
    assert len(calls) == 1


def test_worker_mode_calls_main_directly(monkeypatch):
    monkeypatch.setenv("AI_TASK_RUNNER_WORKER", "1")
    monkeypatch.setattr(ai_task_runner, "main", lambda argv: 7)
    assert ai_task_runner._supervise(["--anything"]) == 7


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
        [sys.executable, "-c", "print('ok')"],
        tmp_path,
        10,
    )

    assert result.return_code == 0
    assert [event["type"] for event in events] == [
        "runner.process.start", "runner.process.exit"
    ]
    assert events[0]["pid"] > 0
    assert events[0]["return_code"] is None
    assert events[1]["pid"] == events[0]["pid"]
    assert events[1]["return_code"] == 0
    assert not (work / process_module.ACTIVE_PROCESS_FILE).exists()


def test_cleanup_orphan_only_for_matching_worker(tmp_path, monkeypatch):
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    active = work / "active-process"
    active.write_text("100 200", encoding="ascii")
    request = SimpleNamespace(project_root=str(tmp_path), work_dir=".ai-task-runner")
    calls = []
    if ai_task_runner.os.name == "nt":
        monkeypatch.setattr(
            ai_task_runner.subprocess,
            "run",
            lambda command, **kwargs: calls.append(command),
        )
    else:
        monkeypatch.setattr(
            ai_task_runner.os,
            "killpg",
            lambda pid, sig: calls.append((pid, sig)),
        )

    ai_task_runner._cleanup_orphan(request, 999)
    assert calls == []
    assert active.exists()

    ai_task_runner._cleanup_orphan(request, 100)
    assert calls
    child = calls[0][2] if ai_task_runner.os.name == "nt" else calls[0][0]
    assert str(child) == "200"
    assert not active.exists()
