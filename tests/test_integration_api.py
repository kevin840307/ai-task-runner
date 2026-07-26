import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runner_api import RunConfig, RunRequest, run


def _validator(path: Path) -> Path:
    path.write_text(
        "import argparse\n"
        "p=argparse.ArgumentParser();p.add_argument('--project-root');"
        "p.add_argument('--state-file');p.parse_args();raise SystemExit(0)\n",
        encoding="utf-8",
    )
    return path


def _fake_command() -> str:
    return f'"{sys.executable}" "{ROOT / "tests/fake_agent.py"}"'


def test_programmatic_api_runs_without_terminal_and_emits_events(tmp_path):
    events = []
    result = run(
        RunConfig(
            goal="x",
            project_root=str(tmp_path),
            validator=str(_validator(tmp_path / "validator.py")),
            backend="qwen",
            command=_fake_command(),
            retry_delay=0,
        ),
        on_event=events.append,
    )

    assert result.exit_code == 0
    assert result.completed is True
    assert result.states[0]["completed"] is True
    assert any(event["type"] == "runner.progress" for event in events)
    assert any(event["type"] == "runner.status" for event in events)
    assert all(event["schema_version"] == 1 for event in events)
    assert all(event["runner_version"] == "1.1.1" for event in events)


def test_cli_json_events_are_machine_readable_json_lines(tmp_path):
    validator = _validator(tmp_path / "validator.py")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ai_task_runner.py"),
            "--backend",
            "qwen",
            "--goal",
            "x",
            "--project-root",
            str(tmp_path),
            "--validator",
            str(validator),
            "--command",
            _fake_command(),
            "--retry-delay",
            "0",
            "--json-events",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert events
    assert all(event["schema_version"] == 1 for event in events)
    assert all(event["runner_version"] == "1.1.1" for event in events)
    assert any(event["type"] == "runner.status" for event in events)
    assert events[-1]["status"] == "全部完成"


def test_yaml_api_events_include_script_item_context(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text("- prompt: first\n  validator: ai\n", encoding="utf-8")
    events = []

    result = run(
        RunConfig(
            project_root=str(tmp_path),
            script=str(script),
            backend="qwen",
            command=_fake_command(),
            retry_delay=0,
        ),
        on_event=events.append,
    )

    assert result.completed is True
    assert any(event["type"] == "script.item_started" for event in events)
    task_events = [event for event in events if event["type"].startswith("runner.")]
    assert task_events
    assert all(event["script_index"] == 1 for event in task_events)
    assert all(event["script_total"] == 1 for event in task_events)


def test_retry_loop_survives_many_transient_failures():
    from errors import RunnerError
    from runner_support import LiveUI, retry_model_call

    attempts = 0

    def action():
        nonlocal attempts
        attempts += 1
        if attempts <= 100:
            raise RunnerError("temporary model outage")
        return "ok"

    result = retry_model_call(
        action,
        LiveUI(human_output=False),
        "retry",
        "",
        0,
        0,
    )
    assert result == "ok"
    assert attempts == 101


def test_event_callback_failure_does_not_stop_runner(tmp_path):
    def broken_callback(event):
        raise RuntimeError("UI disconnected")

    result = run(
        RunConfig(
            goal="x",
            project_root=str(tmp_path),
            validator=str(_validator(tmp_path / "validator.py")),
            backend="qwen",
            command=_fake_command(),
            retry_delay=0,
        ),
        on_event=broken_callback,
    )
    assert result.completed is True


def test_yaml_event_callback_failure_does_not_stop_runner(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text("- prompt: first\n  validator: ai\n", encoding="utf-8")

    def broken_callback(event):
        raise RuntimeError("UI disconnected")

    result = run(
        RunConfig(
            project_root=str(tmp_path),
            script=str(script),
            backend="qwen",
            command=_fake_command(),
            retry_delay=0,
        ),
        on_event=broken_callback,
    )
    assert result.completed is True


def test_json_event_output_disconnect_does_not_stop_ui(monkeypatch):
    from runner_support import LiveUI

    def broken_print(*args, **kwargs):
        raise BrokenPipeError("consumer disconnected")

    monkeypatch.setattr("builtins.print", broken_print)
    ui = LiveUI(json_events=True, human_output=False)
    ui.set("running", "test")
    assert ui.json_events is False


def test_cli_delegates_to_shared_run_entry(monkeypatch, tmp_path):
    import ai_task_runner
    from runner_api import RunResult

    captured = []

    def fake_run(request, on_event=None):
        captured.append(request)
        return RunResult(exit_code=0, state_files=(), states=())

    monkeypatch.setattr(ai_task_runner, "run", fake_run)
    code = ai_task_runner.main([
        "--goal", "x",
        "--project-root", str(tmp_path),
        "--validator", "ai",
        "--backend", "opencode",
    ])

    assert code == 0
    assert len(captured) == 1
    assert captured[0].goal == "x"
    assert captured[0].backend == "opencode"
    assert captured[0].human_output is True


def test_shared_run_entry_accepts_json_like_request(tmp_path):
    events = []
    result = run(
        {
            "goal": "x",
            "project_root": str(tmp_path),
            "validator": str(_validator(tmp_path / "validator.py")),
            "backend": "qwen",
            "command": _fake_command(),
            "retry_delay": 0,
        },
        on_event=events.append,
    )

    assert result.completed is True
    assert any(event["type"] == "runner.status" for event in events)


@pytest.mark.parametrize(
    ("run_request", "message"),
    [
        (RunRequest(), "goal is required"),
        (
            RunRequest(goal="x", validator="ai", resume=True, force_new=True),
            "cannot both be true",
        ),
        (
            RunRequest(goal="x", validator="ai", work_dir="../outside"),
            "inside project_root",
        ),
        (
            RunRequest(goal="x", validator="ai", agent_args="--model"),
            "agent_args must be a list",
        ),
        (
            RunRequest(goal="x", validator="ai", retry_wait=10, retry_max_wait=5),
            "greater than or equal",
        ),
    ],
)
def test_shared_entry_rejects_invalid_requests_early(run_request, message):
    with pytest.raises(ValueError, match=message):
        run(run_request)
