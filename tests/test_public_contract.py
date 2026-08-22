"""Public naming, compatibility, and long-running control-loop tests."""
from __future__ import annotations

import json
import sys

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runner.agent import Agent, AgentClient
from runner.backends import AgentBackend, Backend, default_command
from runner.defaults import DEFAULT_QWEN_COMMAND
from runner.api import RunRequest, __version__, run
from runner.models import RunState, State, Task
from ai_task_runner_validator import ValidatorReport



def _fake_command() -> str:
    return f'"{sys.executable}" "{ROOT / "tests/fake_agent.py"}"'


def _validator(path: Path) -> Path:
    path.write_text(
        "import argparse\n"
        "p=argparse.ArgumentParser();p.add_argument('--project-root');"
        "p.add_argument('--state-file');p.parse_args();raise SystemExit(0)\n",
        encoding="utf-8",
    )
    return path


def test_canonical_public_names_are_stable():
    assert __version__ == "1.2.12"
    assert State is RunState
    assert Agent is AgentClient
    assert Backend is AgentBackend
    assert ValidatorReport.__name__ == "ValidatorReport"


def test_validator_helper_is_installable_public_module():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "ai-task-runner"' in pyproject
    assert 'packages = ["runner", "runner.backends"]' in pyproject
    assert '"ai_task_runner_validator"' in pyproject
    assert '"ai_task_runner"' in pyproject


def test_run_state_json_contract_is_unchanged():
    state = RunState(
        run_id="run-1",
        goal="goal",
        project_root="project",
        tasks=[Task(id="t1", title="title", description="description")],
    )
    payload = state.dump()
    assert payload["run_id"] == "run-1"
    assert payload["tasks"][0]["status"] == "pending"
    assert "agent_session_id" in payload
    assert payload["stage"] == "created"
    assert payload["validator_failure_count"] == 0
    assert RunState.load(json.loads(json.dumps(payload))).dump() == payload

    old_payload = dict(payload)
    for key in (
        "stage",
        "stage_started_at",
        "last_activity_at",
        "last_error",
        "validator_failure_key",
        "validator_failure_count",
    ):
        old_payload.pop(key)
    loaded = RunState.load(json.loads(json.dumps(old_payload)))
    assert loaded.stage == "created"
    assert loaded.validator_failure_count == 0


def test_same_python_process_can_run_multiple_complete_jobs(tmp_path):
    for index in range(5):
        project = tmp_path / f"project-{index}"
        project.mkdir()
        events: list[dict] = []
        result = run(
            RunRequest(
                goal=f"job-{index}",
                project_root=str(project),
                validator=str(_validator(project / "validator.py")),
                backend="qwen",
                command=_fake_command(),
                retry_delay=0,
                retry_wait=0,
                retry_max_wait=0,
            ),
            on_event=events.append,
        )
        assert result.completed is True
        assert result.states[0]["goal"] == f"job-{index}"
        assert events[-1]["status"] == "全部完成"


def test_retry_loop_is_iterative_across_one_thousand_failures():
    from runner.errors import RunnerError
    from runner.support import LiveUI, retry_model_call

    attempts = 0

    def action() -> str:
        nonlocal attempts
        attempts += 1
        if attempts <= 1000:
            raise RunnerError("temporary outage")
        return "ok"

    assert retry_model_call(
        action,
        LiveUI(human_output=False),
        "retry",
        "",
        0,
        0,
    ) == "ok"
    assert attempts == 1001


def test_core_uses_descriptive_canonical_names():
    core = (ROOT / "runner" / "core.py").read_text(encoding="utf-8")
    support = (ROOT / "runner" / "support.py").read_text(encoding="utf-8")
    cli = (ROOT / "ai_task_runner.py").read_text(encoding="utf-8")

    assert "from .models import RunState, Task" in core
    assert "from .agent import AgentClient" in core
    assert "from .model_results import (" in support
    assert "from .prompting import (" not in support
    assert "from runner.prompting import (" in cli
    assert "from runner.api import RunRequest, run" in cli


def test_support_keeps_model_result_import_compatibility():
    from runner import model_results
    from runner import support

    assert support.parse_tasks is model_results.parse_tasks
    assert support.parse_review is model_results.parse_review
    assert support.parse_ai_validation is model_results.parse_ai_validation


def test_agent_timeout_is_part_of_public_request_contract():
    request = RunRequest(goal="x", validator="ai")
    assert request.agent_timeout == 7200
    assert request.to_namespace().agent_timeout == 7200
    assert request.planning_timeout == 600
    assert request.to_namespace().planning_timeout == 600
    assert request.agent_idle_after_change_timeout == 900
    assert request.to_namespace().agent_idle_after_change_timeout == 900
    assert request.validator_timeout == 1200
    assert request.to_namespace().validator_timeout == 1200
    assert default_command("qwen") == DEFAULT_QWEN_COMMAND == "qwen.cmd"

    RunRequest(goal="x", validator="ai", agent_timeout=0).validate()
    RunRequest(goal="x", validator="ai", planning_timeout=0).validate()
    RunRequest(goal="x", validator="ai", agent_idle_after_change_timeout=0).validate()
    with pytest.raises(ValueError, match="agent_timeout"):
        RunRequest(goal="x", validator="ai", agent_timeout=-1).validate()
    with pytest.raises(ValueError, match="planning_timeout"):
        RunRequest(goal="x", validator="ai", planning_timeout=-1).validate()
    with pytest.raises(ValueError, match="agent_idle_after_change_timeout"):
        RunRequest(goal="x", validator="ai", agent_idle_after_change_timeout=-1).validate()
