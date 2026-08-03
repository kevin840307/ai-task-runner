"""Abnormal-path and 24-hour resilience regression matrix."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runner.agent import SESSION_INVALID_MARKERS, is_session_invalid_error
from runner.backends.base import AgentBackend, BackendError, BackendResult
from runner.errors import RunnerError
from runner.process_control import run_process
from runner.api import RunRequest, run
from runner.models import RunState, Task
from runner.support import (
    LiveUI,
    parse_ai_validation,
    parse_json,
    parse_review,
    parse_tasks,
    protected_ask,
    readonly_project_call,
    retry_model_call,
    run_file_validator,
)


def _fake_command(name: str = "fake_agent.py") -> str:
    return f'"{sys.executable}" "{ROOT / "tests" / name}"'


def _passing_validator(path: Path) -> Path:
    path.write_text(
        "import argparse\n"
        "p=argparse.ArgumentParser();p.add_argument('--project-root');"
        "p.add_argument('--state-file');p.parse_args();raise SystemExit(0)\n",
        encoding="utf-8",
    )
    return path


def test_protected_ask_stops_and_restores_on_protected_change(tmp_path):
    protected = tmp_path / "validator.py"
    protected.write_text("original", encoding="utf-8")

    class Agent:
        def ask(self, prompt, idle_timeout_after_change=0, change_detected=None):
            del prompt, idle_timeout_after_change
            protected.write_text("changed", encoding="utf-8")
            assert change_detected is not None
            change_detected()
            return "unreachable"

    with pytest.raises(RunnerError, match="protected file modified"):
        protected_ask(Agent(), "go", [protected], 1, lambda: False)

    assert protected.read_text(encoding="utf-8") == "original"


def test_command_not_found_does_not_leave_new_state(tmp_path):
    with pytest.raises(RunnerError, match="command not found"):
        run(RunRequest(
            goal="x",
            project_root=str(tmp_path),
            validator="ai",
            command=str(tmp_path / "missing-command"),
        ))
    assert not (tmp_path / ".ai-task-runner" / "state.json").exists()


def test_resume_missing_state_has_clear_error(tmp_path):
    with pytest.raises(RunnerError, match="resume state not found"):
        run(RunRequest(
            project_root=str(tmp_path),
            validator="ai",
            command=_fake_command(),
            resume=True,
        ))


def test_resume_corrupt_state_has_clear_error(tmp_path):
    state = tmp_path / ".ai-task-runner" / "state.json"
    state.parent.mkdir()
    state.write_text("{broken", encoding="utf-8")
    with pytest.raises(RunnerError, match="invalid resume state"):
        run(RunRequest(
            project_root=str(tmp_path),
            validator="ai",
            command=_fake_command(),
            resume=True,
        ))


def test_resume_rejects_state_from_another_project(tmp_path):
    state = tmp_path / ".ai-task-runner" / "state.json"
    state.parent.mkdir()
    state.write_text(json.dumps({
        "run_id": "r",
        "goal": "g",
        "project_root": str(tmp_path / "other"),
    }), encoding="utf-8")
    with pytest.raises(RunnerError, match="different project_root"):
        run(RunRequest(
            project_root=str(tmp_path),
            validator="ai",
            command=_fake_command(),
            resume=True,
        ))


@pytest.mark.parametrize("marker", SESSION_INVALID_MARKERS)
def test_all_documented_session_invalid_markers_are_detected(marker):
    assert is_session_invalid_error(f"ERROR: {marker.upper()}")


def test_unrelated_error_does_not_clear_session_classification():
    assert not is_session_invalid_error("network temporarily unavailable")


def test_retry_does_not_swallow_keyboard_interrupt():
    def stop():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        retry_model_call(stop, LiveUI(human_output=False), "x", "", 0, 0)


def test_json_parser_accepts_fenced_and_embedded_objects():
    assert parse_json('```json\n{"passed": true}\n```')["passed"] is True
    assert parse_json('prefix {"completed": false, "reason": "x"} suffix')["completed"] is False


def test_schema_parsers_reject_wrong_boolean_types():
    with pytest.raises(RunnerError, match="review.completed"):
        parse_review('{"completed":"true","reason":"x","missing_items":[]}')
    with pytest.raises(RunnerError, match="validator.passed"):
        parse_ai_validation('{"passed":1,"reason":"x","missing_items":[]}')
    with pytest.raises(RunnerError, match="acceptance_criteria"):
        parse_tasks('{"tasks":[{"title":"x","description":"y","acceptance_criteria":[]}]}', 1)


def test_run_state_rejects_invalid_persisted_values():
    with pytest.raises(ValueError, match="state.current"):
        RunState.load({
            "run_id": "r",
            "goal": "g",
            "project_root": "/p",
            "current": 2,
            "tasks": [
                {"id": "t", "title": "x", "description": "y"},
            ],
        })
    with pytest.raises(ValueError, match="status"):
        RunState.load({
            "run_id": "r",
            "goal": "g",
            "project_root": "/p",
            "tasks": [
                {"id": "t", "title": "x", "description": "y", "status": "running"},
            ],
        })


def test_readonly_guard_restores_create_modify_delete_and_rename(tmp_path):
    work = tmp_path / ".ai-task-runner"
    keep = tmp_path / "keep.txt"
    deleted = tmp_path / "deleted.txt"
    renamed = tmp_path / "renamed.txt"
    keep.write_text("original", encoding="utf-8")
    deleted.write_text("restore", encoding="utf-8")
    renamed.write_text("rename", encoding="utf-8")

    def mutate():
        keep.write_text("changed", encoding="utf-8")
        deleted.unlink()
        renamed.rename(tmp_path / "new-name.txt")
        (tmp_path / "created.txt").write_text("new", encoding="utf-8")
        return "ok"

    result, changed = readonly_project_call(mutate, tmp_path, work)
    assert result == "ok"
    assert keep.read_text() == "original"
    assert deleted.read_text() == "restore"
    assert renamed.read_text() == "rename"
    assert not (tmp_path / "new-name.txt").exists()
    assert not (tmp_path / "created.txt").exists()
    assert {"keep.txt", "deleted.txt", "renamed.txt", "new-name.txt", "created.txt"} <= set(changed)


def test_agent_timeout_does_not_wait_for_detached_stdout_holder(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX detached-session regression")
    child_pid = tmp_path / "child.pid"
    code = (
        "import subprocess,sys,time,pathlib; "
        f"p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'], start_new_session=True); "
        f"pathlib.Path({str(child_pid)!r}).write_text(str(p.pid)); "
        "print('parent ready', flush=True); time.sleep(30)"
    )
    started = time.monotonic()
    result = run_process([sys.executable, "-c", code], tmp_path, 1)
    elapsed = time.monotonic() - started
    assert result.timed_out is True
    assert elapsed < 8
    if child_pid.exists():
        try:
            os.kill(int(child_pid.read_text()), 9)
        except ProcessLookupError:
            pass


def test_agent_timeout_kills_normal_child_process_tree(tmp_path):
    marker = tmp_path / "child-survived.txt"
    child = f"import time,pathlib; time.sleep(2); pathlib.Path({str(marker)!r}).write_text('bad')"
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
    )
    result = run_process([sys.executable, "-c", parent], tmp_path, 1)
    assert result.timed_out is True
    time.sleep(2.5)
    assert not marker.exists()


def test_process_idle_after_change_timeout_stops_before_full_timeout(tmp_path):
    marker = tmp_path / "changed.txt"
    code = (
        "import pathlib,time; "
        f"pathlib.Path({str(marker)!r}).write_text('changed'); "
        "time.sleep(30)"
    )
    seen = False

    def changed() -> bool:
        nonlocal seen
        if marker.exists() and not seen:
            seen = True
            return True
        return False

    started = time.monotonic()
    result = run_process(
        [sys.executable, "-c", code],
        tmp_path,
        timeout=20,
        idle_timeout_after_change=0.2,
        change_detected=changed,
    )
    assert result.timed_out is True
    assert result.idle_timed_out is True
    assert time.monotonic() - started < 5


def test_process_idle_without_initial_activity_stops_before_full_timeout(tmp_path):
    started = time.monotonic()
    result = run_process(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path,
        timeout=20,
        idle_timeout_after_change=0.2,
        change_detected=lambda: False,
    )
    assert result.timed_out is True
    assert result.idle_timed_out is True
    assert time.monotonic() - started < 5


def test_process_stdout_heartbeat_keeps_watchdog_alive(tmp_path):
    code = (
        "import time; "
        "print('first', flush=True); "
        "time.sleep(0.05); "
        "print('second', flush=True)"
    )
    result = run_process(
        [sys.executable, "-c", code],
        tmp_path,
        timeout=20,
        idle_timeout_after_change=0.3,
        change_detected=lambda: False,
    )
    assert result.timed_out is False
    assert "first" in result.output
    assert "second" in result.output


def test_process_idle_after_stdout_stops_before_full_timeout(tmp_path):
    code = "import time; print('ready', flush=True); time.sleep(30)"
    started = time.monotonic()
    result = run_process(
        [sys.executable, "-c", code],
        tmp_path,
        timeout=20,
        idle_timeout_after_change=0.2,
        change_detected=lambda: False,
    )
    assert result.timed_out is True
    assert result.idle_timed_out is True
    assert "ready" in result.output
    assert time.monotonic() - started < 5


def test_process_unexpected_error_cleans_up_process_tree(tmp_path, monkeypatch):
    import runner.process_control as process_control

    killed = []

    class FakeProcess:
        pid = 123
        returncode = None

        def communicate(self, **kwargs):
            raise RuntimeError("boom")

        def poll(self):
            return None

    fake_process = FakeProcess()
    monkeypatch.setattr(
        process_control.subprocess,
        "Popen",
        lambda *args, **kwargs: fake_process,
    )
    monkeypatch.setattr(
        process_control,
        "terminate_process_tree",
        lambda process: killed.append(process.pid),
    )

    with pytest.raises(RuntimeError):
        run_process(["agent"], tmp_path, timeout=10)

    assert killed == [123]


def test_file_validator_timeout_kills_child_tree_and_preserves_partial_output(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    marker = tmp_path / "validator-child-survived.txt"
    validator = tmp_path / "validator.py"
    child_code = (
        "import time,pathlib; "
        "time.sleep(2); "
        f"pathlib.Path({str(marker)!r}).write_text('bad')"
    )
    validator.write_text(
        "import argparse,subprocess,sys,time\n"
        "p=argparse.ArgumentParser();p.add_argument('--project-root');p.add_argument('--state-file');a=p.parse_args()\n"
        "print('validator-started', flush=True)\n"
        "open(a.state_file,'w').write('changed')\n"
        f"code={child_code!r}\n"
        "subprocess.Popen([sys.executable,'-c',code])\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    passed, output = run_file_validator(
        validator, tmp_path, state_file, 1, [], [state_file]
    )
    assert passed is False
    assert "validator timeout after 1 seconds" in output
    assert "validator-started" in output
    assert state_file.read_text() == "{}"
    time.sleep(2.5)
    assert not marker.exists()


def test_all_model_stages_timeout_once_then_recover(tmp_path, monkeypatch):
    state_dir = Path(tempfile.mkdtemp(prefix="timeout-stages-", dir=tmp_path.parent))
    monkeypatch.setenv("TIMEOUT_STAGE_STATE_DIR", str(state_dir))
    result = run(RunRequest(
        goal="x",
        project_root=str(tmp_path),
        validator="ai",
        command=_fake_command("timeout_stage_agent.py"),
        agent_timeout=2,
        planning_timeout=2,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
    ))
    assert result.completed is True
    assert (state_dir / "plan.count").read_text() == "1"
    assert (state_dir / "execute.count").read_text() == "1"
    for stage in ("review", "validator"):
        assert (state_dir / f"{stage}.count").read_text() == "2"


def test_review_uses_planning_timeout_not_agent_timeout(tmp_path, monkeypatch):
    state_dir = Path(tempfile.mkdtemp(prefix="review-timeout-", dir=tmp_path.parent))
    monkeypatch.setenv("REVIEW_TIMEOUT_STATE_DIR", str(state_dir))
    result = run(RunRequest(
        goal="x",
        project_root=str(tmp_path),
        validator="ai",
        command=_fake_command("review_timeout_agent.py"),
        agent_timeout=20,
        planning_timeout=1,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
    ))
    assert result.completed is True
    assert (state_dir / "review.count").read_text() == "2"


def test_resume_restores_state_from_external_backup(tmp_path):
    result = run(RunRequest(
        goal="x",
        project_root=str(tmp_path),
        validator="ai",
        command=_fake_command(),
        plan_only=True,
    ))
    assert result.exit_code == 0

    state_file = tmp_path / ".ai-task-runner" / "state.json"
    original = json.loads(state_file.read_text(encoding="utf-8"))
    state_file.write_text('{"completed": true, "project_root": "corrupted"}', encoding="utf-8")

    resumed = run(RunRequest(
        goal="x",
        project_root=str(tmp_path),
        validator="ai",
        command=_fake_command(),
        plan_only=True,
        resume=True,
    ))
    restored = json.loads(state_file.read_text(encoding="utf-8"))
    assert resumed.exit_code == 0
    assert restored["run_id"] == original["run_id"]
    assert restored["completed"] is False


def test_resume_completed_tasks_runs_validator_without_replanning(tmp_path):
    validator = _passing_validator(tmp_path / "validator.py")
    marker = tmp_path / "validator-ran.txt"
    validator.write_text(
        "import argparse\n"
        "p=argparse.ArgumentParser();p.add_argument('--project-root');"
        "p.add_argument('--state-file');args=p.parse_args();"
        f"open({str(marker)!r},'w').write('ran')\n",
        encoding="utf-8",
    )
    state = RunState(
        run_id="resume-before-validator",
        goal="x",
        project_root=str(tmp_path),
        current=1,
        tasks=[
            Task(
                id="t001",
                title="Already done",
                description="Already done",
                acceptance_criteria=["done"],
                status="completed",
            )
        ],
        completed=False,
        stage="reviewing",
    )
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    (work / "state.json").write_text(json.dumps(state.dump()), encoding="utf-8")

    result = run(RunRequest(
        goal="x",
        project_root=str(tmp_path),
        validator=str(validator),
        command=_fake_command("fail_if_called_agent.py"),
        resume=True,
    ))
    assert result.exit_code == 0
    assert marker.read_text(encoding="utf-8") == "ran"


def test_execution_idle_after_change_goes_to_review(tmp_path, monkeypatch):
    state_dir = Path(tempfile.mkdtemp(prefix="idle-after-change-", dir=tmp_path.parent))
    monkeypatch.setenv("IDLE_AFTER_CHANGE_STATE_DIR", str(state_dir))
    result = run(RunRequest(
        goal="x",
        project_root=str(tmp_path),
        validator="ai",
        command=_fake_command("idle_after_change_agent.py"),
        agent_timeout=20,
        agent_idle_after_change_timeout=0.2,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
    ))
    assert result.completed is True
    assert (state_dir / "execute.count").read_text() == "1"
    assert (state_dir / "review.count").read_text() == "1"
    assert result.states[0]["tasks"][0]["attempts"] == 1


def test_max_attempts_stops_incomplete_task_with_exit_code_2(tmp_path, monkeypatch):
    state_dir = Path(tempfile.mkdtemp(prefix="max-attempts-", dir=tmp_path.parent))
    monkeypatch.setenv("SCENARIO", "stagnation")
    monkeypatch.setenv("SCENARIO_STATE_DIR", str(state_dir))
    result = run(RunRequest(
        goal="x",
        project_root=str(tmp_path),
        validator="ai",
        command=_fake_command("scenario_agent.py"),
        max_attempts=2,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
    ))
    assert result.exit_code == 2
    assert result.completed is False
    assert result.states[0]["tasks"][0]["attempts"] == 2


def test_max_cycles_stops_after_first_failed_validation(tmp_path, monkeypatch):
    state_dir = Path(tempfile.mkdtemp(prefix="max-cycles-", dir=tmp_path.parent))
    monkeypatch.setenv("SCENARIO", "ai_replan")
    monkeypatch.setenv("SCENARIO_STATE_DIR", str(state_dir))
    result = run(RunRequest(
        goal="x",
        project_root=str(tmp_path),
        validator="ai",
        command=_fake_command("scenario_agent.py"),
        max_cycles=1,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
    ))
    assert result.exit_code == 3
    assert result.completed is False
    assert result.states[0]["cycle"] == 2


def test_validator_arguments_are_forwarded(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import argparse\n"
        "p=argparse.ArgumentParser();p.add_argument('--project-root');p.add_argument('--state-file');p.add_argument('--token');a=p.parse_args()\n"
        "raise SystemExit(0 if a.token == 'ok' else 1)\n",
        encoding="utf-8",
    )
    assert run_file_validator(
        validator, tmp_path, state_file, 10, ["--token", "ok"], [state_file]
    )[0] is True


def test_file_validator_clears_previous_reports_before_run(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    report_dir = tmp_path / ".ai-task-runner" / "validator-reports"
    report_dir.mkdir(parents=True)
    (report_dir / "old.txt").write_text("stale", encoding="utf-8")

    validator = tmp_path / "validator.py"
    validator.write_text(
        "import argparse,pathlib\n"
        "p=argparse.ArgumentParser();p.add_argument('--project-root');p.add_argument('--state-file');a=p.parse_args()\n"
        "root=pathlib.Path(a.project_root)\n"
        "reports=root/'.ai-task-runner'/'validator-reports'\n"
        "assert not (reports/'old.txt').exists(), 'stale report was not cleared'\n"
        "reports.mkdir(parents=True, exist_ok=True)\n"
        "(reports/'latest.txt').write_text('new', encoding='utf-8')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )

    passed, output = run_file_validator(
        validator, tmp_path, state_file, 10, [], [state_file]
    )

    assert passed is True, output
    assert not (report_dir / "old.txt").exists()
    assert (report_dir / "latest.txt").read_text(encoding="utf-8") == "new"


def test_file_validator_large_output_keeps_summary_and_report_reference(tmp_path):
    from runner.prompting import bounded_text
    from runner.support import MAX_VALIDATOR_OUTPUT_CHARS

    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import argparse,pathlib\n"
        "p=argparse.ArgumentParser();p.add_argument('--project-root');p.add_argument('--state-file');a=p.parse_args()\n"
        "root=pathlib.Path(a.project_root)\n"
        "reports=root/'.ai-task-runner'/'validator-reports'/'large-output'\n"
        "reports.mkdir(parents=True, exist_ok=True)\n"
        "(reports/'details.txt').write_text('full details', encoding='utf-8')\n"
        "print('VALIDATION_FAILED')\n"
        "print('errors: 1')\n"
        "print('warnings: 0')\n"
        "print('report_dir: .ai-task-runner/validator-reports/large-output')\n"
        "print('Full report: .ai-task-runner/validator-reports/large-output/details.txt')\n"
        "print('A' * 30000)\n"
        "print('END_MARKER')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )

    passed, output = run_file_validator(
        validator, tmp_path, state_file, 10, [], [state_file]
    )
    bounded = bounded_text(output, MAX_VALIDATOR_OUTPUT_CHARS)

    assert passed is False
    assert "VALIDATION_FAILED" in output
    assert "Full report: .ai-task-runner/validator-reports/large-output/details.txt" in output
    assert (tmp_path / ".ai-task-runner" / "validator-reports" / "large-output" / "details.txt").is_file()
    assert len(bounded) <= MAX_VALIDATOR_OUTPUT_CHARS
    assert "VALIDATION_FAILED" in bounded
    assert "Full report: .ai-task-runner/validator-reports/large-output/details.txt" in bounded
    assert "END_MARKER" in bounded


def test_unknown_mapping_field_is_rejected_before_execution():
    with pytest.raises(ValueError, match="unknown request fields"):
        run({"goal": "x", "validator": "ai", "unexpected": True})


def test_force_new_setup_failure_preserves_previous_state(tmp_path):
    state = tmp_path / ".ai-task-runner" / "state.json"
    state.parent.mkdir()
    previous = {
        "run_id": "old-run",
        "goal": "old-goal",
        "project_root": str(tmp_path),
    }
    state.write_text(json.dumps(previous), encoding="utf-8")
    with pytest.raises(RunnerError, match="command not found"):
        run(RunRequest(
            goal="new-goal",
            project_root=str(tmp_path),
            validator="ai",
            command=str(tmp_path / "missing-command"),
            force_new=True,
        ))
    assert json.loads(state.read_text()) == previous


def test_invalid_yaml_fails_before_item_state_is_created(tmp_path):
    from runner.script_runner import load_yaml_script

    script = tmp_path / "tasks.yaml"
    script.write_text("prompt: not-an-array\nvalidator: ai\n", encoding="utf-8")
    with pytest.raises(RunnerError, match="non-empty array"):
        load_yaml_script(script)
    assert not (tmp_path / ".ai-task-runner" / "script").exists()


def test_windows_process_tree_uses_taskkill_tree_flags(monkeypatch):
    import runner.process_control as process_control
    from types import SimpleNamespace

    calls = []

    class FakeProcess:
        pid = 123

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            raise AssertionError("direct kill should not be needed")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(process_control, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(process_control.subprocess, "run", fake_run)
    process_control.terminate_process_tree(FakeProcess())

    assert calls[0][0] == ["taskkill", "/PID", "123", "/T", "/F"]
    assert calls[0][1]["timeout"] == process_control.TASKKILL_TIMEOUT_SECONDS


def test_file_validator_nonzero_exit_preserves_diagnostics(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import argparse\n"
        "p=argparse.ArgumentParser();p.add_argument('--project-root');p.add_argument('--state-file');p.parse_args()\n"
        "print('FAILED: expected A, actual B')\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    passed, output = run_file_validator(
        validator, tmp_path, state_file, 10, [], [state_file]
    )
    assert passed is False
    assert "FAILED: expected A, actual B" in output
