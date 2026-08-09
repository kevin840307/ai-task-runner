from pathlib import Path
from types import SimpleNamespace

import pytest


def test_no_change_still_reviews_and_preserves_executor_session(tmp_path, monkeypatch):
    import runner.core as core
    from runner.models import RunState, Task

    task = Task(
        id="c01-t001",
        title="Read-only task",
        description="Inspect current state",
        deliverable="Inspection completed",
        acceptance_criteria=["Current state inspected"],
    )
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(max_attempts=0, retry_delay=0)
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.state = RunState(
        run_id="r", goal="g", project_root=str(tmp_path), tasks=[task]
    )
    runner.agent = SimpleNamespace(session_id="task-session")
    runner.ui = SimpleNamespace(set=lambda *args: None)
    runner._save_state = lambda: None
    runner._set_stage = lambda *args: None
    runner._execute_current_task = lambda current: "inspection complete"
    reviews = []
    runner._review_current_task = lambda current, output: reviews.append((current.id, output)) or {
        "completed": True, "reason": "already satisfied", "missing_items": []
    }

    monkeypatch.setattr(core, "project_manifest", lambda *args: {})
    monkeypatch.setattr(core, "changed_project_files", lambda *args: [])
    monkeypatch.setattr(core, "show_todo", lambda *args: None)

    assert runner._run_pending_tasks() is None
    assert reviews == [(task.id, "inspection complete")]
    assert task.status == "completed"
    assert task.review_skipped is False
    assert runner.agent.session_id == "task-session"
    assert runner.state.agent_session_id == "task-session"


def test_validator_infrastructure_error_retries_without_repair_cycle(tmp_path):
    import runner.core as core
    from runner.errors import RunnerError
    from runner.models import RunState

    stages = []
    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(retry_delay=0, max_cycles=0)
    runner.ai_validation = False
    runner.validator = tmp_path / "validator.py"
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    runner.ui = SimpleNamespace(
        start=lambda *args: None,
        stop=lambda *args: None,
        set=lambda *args: None,
    )
    runner._save_state = lambda: None
    runner._set_stage = lambda stage, detail="": stages.append((stage, detail))
    runner._run_validator = lambda: (_ for _ in ()).throw(
        RunnerError("validator process unavailable")
    )

    assert runner._validate_cycle() is None
    assert runner.state.cycle == 1
    assert runner.state.completed is False
    assert any(stage == "validator_retry_wait" for stage, _ in stages)


def test_loop_detection_reuses_once_then_resets_repeated_session():
    from runner.agent import AgentClient, AgentError
    from runner.backends import BackendError

    class Backend:
        timeout = 1

        def ask(self, *args, **kwargs):
            raise BackendError("Loop detection halted the run")

    agent = AgentClient.__new__(AgentClient)
    agent._backend = Backend()
    agent.backend = "qwen"
    agent.base_command = []
    agent.root = Path(".")
    agent.extra_args = []
    agent.session_id = "old-session"
    agent.timeout = 1

    with pytest.raises(AgentError, match="Loop detection halted"):
        agent.ask("p")
    assert agent.session_id == "old-session"

    with pytest.raises(AgentError, match="Loop detection halted"):
        agent.ask("p")
    assert agent.session_id == ""


def test_planning_can_preserve_loop_session_for_no_tool_finalize():
    from runner.agent import AgentClient, AgentError
    from runner.backends import BackendError

    class Backend:
        timeout = 1

        def ask(self, *args, **kwargs):
            raise BackendError(
                "Loop detection halted the run",
                session_id="planning-session",
            )

    agent = AgentClient.__new__(AgentClient)
    agent._backend = Backend()
    agent.backend = "qwen"
    agent.base_command = []
    agent.root = Path(".")
    agent.extra_args = []
    agent.session_id = ""
    agent.timeout = 1

    with pytest.raises(AgentError, match="Loop detection halted"):
        agent.ask("p")
    assert agent.session_id == "planning-session"


def test_prompt_history_is_bounded_to_recent_items(tmp_path):
    from runner.models import RunState, Task
    from runner.prompting import MAX_PROMPT_HISTORY_ITEMS, completed_titles

    state = RunState(
        run_id="r",
        goal="g",
        project_root=str(tmp_path),
        tasks=[
            Task(
                id=f"c01-t{index:03d}",
                title=f"task-{index}",
                description="d",
                status="completed",
            )
            for index in range(MAX_PROMPT_HISTORY_ITEMS + 5)
        ],
        current=MAX_PROMPT_HISTORY_ITEMS + 5,
    )
    titles = completed_titles(state)
    assert len(titles) == MAX_PROMPT_HISTORY_ITEMS
    assert titles[0] == "task-5"


def test_final_ai_quorum_configuration_is_unchanged():
    from runner.api import RunRequest

    request = RunRequest(
        goal="g",
        validator="ai",
        final_ai_validations=3,
        final_ai_required_passes=2,
    )
    request.validate()
    assert request.final_ai_validations == 3
    assert request.final_ai_required_passes == 2
