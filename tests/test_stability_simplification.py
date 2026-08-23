from pathlib import Path
from types import SimpleNamespace

import pytest


def test_execute_success_without_change_routes_to_review_and_keeps_session():
    from runner.engine.models import Task
    from runner.engine.recovery import Outcome, decide
    from runner.workflow.flow import default_flow

    class S:
        def __init__(self, name): self.name = name

    task = Task(
        id="c01-t001", title="Read-only task", description="Inspect current state",
        deliverable="Inspection completed", acceptance_criteria=["Current state inspected"],
    )
    outcome = Outcome("execute", "pass", output="inspection complete", changed_files=[])
    decision = decide(outcome, task=task, threshold=0)
    planning, execute, review, validate = (S(name) for name in ("planning", "execute", "review", "validate"))
    flow = default_flow(planning, execute, review, validate)
    ctx = SimpleNamespace(state=SimpleNamespace(tasks=[task], current=0, stage="executing", completed=False))
    assert decision.action == "advance"
    assert flow.next("execute", decision.action, ctx) == "review"


def test_validator_infrastructure_error_retries_without_repair_cycle():
    from runner.errors import RunnerError
    from runner.engine.recovery import Outcome, decide

    outcome = Outcome("validate", "error", error=RunnerError("validator process unavailable"))
    decision = decide(outcome, threshold=0)
    assert decision.action == "retry"


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
    from runner.engine.models import RunState, Task
    from runner.agent.prompts import MAX_PROMPT_HISTORY_ITEMS, completed_titles

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
