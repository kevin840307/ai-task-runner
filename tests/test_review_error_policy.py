from types import SimpleNamespace

from runner.engine.models import RunState, Task
from runner.errors import RunnerError
from runner.workflow import reviewing


def _args():
    return SimpleNamespace(
        planning_timeout=1,
        agent_idle_after_change_timeout=0,
        retry_wait=0,
        retry_max_wait=0,
    )


def _state(tmp_path):
    task = Task(id="c01-t001", title="t", description="d")
    return RunState(run_id="r", goal="g", project_root=str(tmp_path), tasks=[task]), task


class FakeAgent:
    def __init__(self):
        self.session_id = ""


def test_review_error_without_session_is_skipped(monkeypatch, tmp_path):
    state, task = _state(tmp_path)
    agent = FakeAgent()
    monkeypatch.setattr(reviewing, "create_agent", lambda *args, **kwargs: agent)
    monkeypatch.setattr(reviewing, "readonly_structured_call", lambda *args, **kwargs: (_ for _ in ()).throw(RunnerError("review unavailable")))

    result = reviewing.review_task(_args(), tmp_path, tmp_path / ".ai-task-runner", state, task, "evidence")
    assert result["completed"] is True
    assert result["review_skipped"] is True


def test_review_explicit_fail_is_not_skipped(monkeypatch, tmp_path):
    state, task = _state(tmp_path)
    agent = FakeAgent()
    monkeypatch.setattr(reviewing, "create_agent", lambda *args, **kwargs: agent)
    monkeypatch.setattr(
        reviewing,
        "readonly_structured_call",
        lambda *args, **kwargs: {"completed": False, "reason": "missing", "missing_items": ["x"]},
    )

    result = reviewing.review_task(_args(), tmp_path, tmp_path / ".ai-task-runner", state, task, "evidence")
    assert result["completed"] is False
    assert result.get("review_skipped", False) is False


def test_review_error_with_session_finalizes(monkeypatch, tmp_path):
    state, task = _state(tmp_path)
    agent = FakeAgent()
    monkeypatch.setattr(reviewing, "create_agent", lambda *args, **kwargs: agent)
    calls = 0

    def ask(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            agent.session_id = "review-session"
            raise RunnerError("review loop")
        return {"completed": True, "reason": "enough", "missing_items": []}

    monkeypatch.setattr(reviewing, "readonly_structured_call", ask)
    result = reviewing.review_task(_args(), tmp_path, tmp_path / ".ai-task-runner", state, task, "evidence")
    assert result["completed"] is True
    assert result.get("review_skipped", False) is False
    assert calls == 2


def test_review_finalize_error_still_skips(monkeypatch, tmp_path):
    state, task = _state(tmp_path)
    agent = FakeAgent()
    monkeypatch.setattr(reviewing, "create_agent", lambda *args, **kwargs: agent)
    calls = 0

    def ask(*args, **kwargs):
        nonlocal calls
        calls += 1
        agent.session_id = "review-session"
        raise RunnerError("review loop")

    monkeypatch.setattr(reviewing, "readonly_structured_call", ask)
    result = reviewing.review_task(_args(), tmp_path, tmp_path / ".ai-task-runner", state, task, "evidence")
    assert result["completed"] is True
    assert result["review_skipped"] is True
    assert calls == 2
