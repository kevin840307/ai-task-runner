from types import SimpleNamespace

from runner.agent.prompts import execution_prompt, render_prompt_template
from runner.engine.models import RunState, Task
from runner.engine.recovery import Outcome, decide, record_execution_progress


def state(attempts=1):
    return RunState(
        run_id="r",
        goal="Build the entire application including many later features.",
        project_root=".",
        tasks=[Task(
            id="c01-t001",
            title="Inspect current structure",
            description="Inspect only",
            deliverable="A factual structure summary",
            acceptance_criteria=["No unrelated implementation"],
            attempts=attempts,
        )],
    )


def test_fresh_execution_prompt_embeds_goal_as_context_not_completed_task_list(tmp_path):
    prompt = execution_prompt(state(), tmp_path, [], include_goal=True)
    assert "Build the entire application including many later features." in prompt
    assert '"completed_tasks"' not in prompt
    assert "Current TODO is the only executable scope" in prompt
    assert "Do not run the final project validator" in prompt
    assert "satisfied or safely improved" in prompt
    assert "ad hoc verification files" in prompt
    assert "remove any temporary artifacts before finishing" in prompt
    assert "Make the smallest maintainable change that satisfies the deliverable and acceptance criteria" in prompt
    assert "If no project change is required, do not modify files" in prompt


def test_execution_prompt_keeps_only_shared_global_constraints(tmp_path):
    shared = "Preserve public interfaces and avoid hardcoding"
    current = state()
    current.tasks[0].acceptance_criteria.append(shared)
    current.tasks.append(Task(
        id="c01-t002",
        title="Later feature",
        description="Do later work",
        deliverable="Later result",
        acceptance_criteria=["Later result exists", shared],
    ))

    prompt = execution_prompt(current, tmp_path, [], include_goal=True)

    assert shared in prompt
    assert "Later feature" not in prompt
    assert "never use it to discover or perform later work" in prompt
    assert "Current TODO is the only executable scope" in prompt


def _runner(tmp_path, task):
    import runner.engine.core as core

    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path), tasks=[task])
    runner.agent = SimpleNamespace(session_id="old-session")
    runner.ui = SimpleNamespace(set=lambda *args: None, bind=lambda *args: None)
    runner.args = SimpleNamespace(task_recovery_threshold=0, retry_delay=0)
    runner._save_state = lambda: None
    runner._save_session = lambda: None
    runner._set_stage = lambda *args: None
    return runner


def test_review_advance_completes_one_task_and_preserves_session(tmp_path):
    from runner.engine import core
    from runner.workflow.stages import StageContext

    task = Task(
        id="c01-t001", title="Focused change", description="Do work",
        deliverable="result", acceptance_criteria=["result exists"],
    )
    runner = _runner(tmp_path, task)
    runner.context = SimpleNamespace(task=task)
    events = []
    monkey_status = __import__("runner.runtime.status", fromlist=["set_status"])
    old = monkey_status.set_status
    monkey_status.set_status = lambda *args: events.append(args)
    try:
        runner._apply("review", Outcome("review", "pass"), decide(Outcome("review", "pass"), task=task, threshold=0))
    finally:
        monkey_status.set_status = old

    assert task.status == "completed"
    assert runner.state.current == 1
    assert runner.agent.session_id == "old-session"
    assert events == [("任務完成", "Focused change")]


def test_execution_error_with_current_changes_reviews_immediately(tmp_path):
    from runner.errors import RunnerError

    task = Task(
        id="c01-t001", title="Current task", description="Do work",
        deliverable="result", acceptance_criteria=["result exists"],
    )
    runner = _runner(tmp_path, task)
    outcome = Outcome("execute", "error", error=RunnerError("failed"), changed_files=["result.txt"])

    assert decide(outcome, task=task, threshold=3).action == "advance"
    assert outcome.status == "error"


def test_old_changes_do_not_count_as_progress_for_current_failed_attempt(tmp_path):
    from runner.errors import RunnerError

    task = Task(
        id="c01-t001", title="Current task", description="Do work",
        deliverable="result", acceptance_criteria=["result exists"],
        changed_files=["saved-from-previous-attempt.txt"],
    )
    runner = _runner(tmp_path, task)
    error = RunnerError("same failure")
    record_execution_progress(task, error, changed=False)
    outcome = Outcome("execute", "error", error=error)

    decision = decide(outcome, task=task, threshold=0)
    runner._prepare_task_retry(task, decision.retry_session, decision.reason)

    assert decision.action == "retry"
    assert task.status == "pending"
    assert task.stagnant_attempts == 1
    assert runner.agent.session_id == "old-session"


def test_three_same_no_change_failures_rebuild_session_but_keep_todo_pending(tmp_path):
    from runner.errors import RunnerError

    task = Task(
        id="c01-t001", title="Current task", description="Do work",
        deliverable="result", acceptance_criteria=["result exists"],
    )
    runner = _runner(tmp_path, task)
    error = RunnerError("same failure")
    outcome = Outcome("execute", "error", error=error)

    for _ in range(2):
        record_execution_progress(task, error, changed=False)
        decision = decide(outcome, task=task, threshold=0)
        assert decision.action == "retry"
        runner._prepare_task_retry(task, decision.retry_session, decision.reason)
    assert runner.agent.session_id == "old-session"

    record_execution_progress(task, error, changed=False)
    decision = decide(outcome, task=task, threshold=0)
    assert decision.action == "retry" and decision.retry_session == "fresh"
    runner._prepare_task_retry(task, decision.retry_session, decision.reason)

    assert task.status == "pending"
    assert task.review_skipped is False
    assert runner.agent.session_id == ""
    assert task.stagnant_attempts == 0


def test_transient_service_error_is_separate_and_does_not_mark_stagnation(tmp_path):
    from runner.agent.client import AgentError

    task = Task(
        id="c01-t001", title="Current task", description="Do work",
        deliverable="result", acceptance_criteria=["result exists"],
    )
    error = AgentError("HTTP 503 service unavailable", transient=True)
    outcome = Outcome("execute", "error", error=error)

    record_execution_progress(task, error, changed=False)

    assert outcome.status == "error"
    assert decide(outcome, task=task, threshold=3).action == "retry"
    assert task.stagnant_attempts == 0
    assert task.progress_key == ""


def test_graph_routes_review_advance_to_next_execute_then_validate():
    from runner.workflow.flow import default_flow

    class S:
        def __init__(self, name): self.name = name

    planning, execute, review, validate = (S(name) for name in ("planning", "execute", "review", "validate"))
    flow = default_flow(planning, execute, review, validate)
    tasks = [
        Task(id="c01-t001", title="one", description="d", deliverable="a", acceptance_criteria=["a"], status="completed"),
        Task(id="c01-t002", title="two", description="d", deliverable="b", acceptance_criteria=["b"]),
    ]
    current = RunState(run_id="r", goal="g", project_root=".", tasks=tasks, current=1)
    ctx = SimpleNamespace(state=current)
    assert flow.next("review", "advance", ctx) == "execute"
    tasks[1].status = "completed"
    current.current = 2
    assert flow.next("review", "advance", ctx) == "validate"


def test_execute_success_advances_to_review_even_without_changed_files():
    task = Task(id="c01-t001", title="check existing result", description="d", deliverable="d", acceptance_criteria=["ok"] )
    outcome = Outcome("execute", "pass", changed_files=[])
    decision = decide(outcome, task=task, threshold=0)
    assert decision.action == "advance"


def test_validator_repair_hint_is_scoped_to_current_todo():
    prompt = render_prompt_template("validator_repair_hint.md", {"repeat_hint": ""})
    lower = prompt.lower()
    assert "first reported validator failure" not in lower
    assert "current todo" in lower
    assert "relevant" in lower
    assert "ignore unrelated validator failures" in lower
    assert "later-todo" in lower


def test_execution_prompt_stops_after_focused_success(tmp_path):
    prompt = execution_prompt(state(), tmp_path, [], include_goal=True)
    assert "smallest focused verification" in prompt
    assert "if it passes, stop immediately" in prompt.lower()
    assert "Do not repeat the same inspection or test hypothesis without new evidence" in prompt
