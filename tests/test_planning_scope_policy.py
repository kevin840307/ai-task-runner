from pathlib import Path
from types import SimpleNamespace
import json

from runner.models import RunState, Task
from runner.prompting import plan_prompt, plan_refine_prompt


def test_planner_requires_self_contained_bounded_tasks(tmp_path: Path):
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    prompt = plan_prompt("g", tmp_path, state, [])

    assert "concrete, observable project result" in prompt
    assert "execution does not need the original goal or planning output" in prompt
    assert "objective stopping evidence" in prompt
    assert "never pad with process tasks" in prompt


def test_plan_refine_is_an_independent_rewrite_contract(tmp_path: Path):
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    tasks = [Task(
        id="c01-t001",
        title="One result",
        description="Create one result",
        deliverable="result",
        acceptance_criteria=["result exists"],
    )]
    prompt = plan_refine_prompt("g", tmp_path, state, tasks)

    assert "independent plan editor" in prompt
    assert "do not defend it" in prompt
    assert "complete replacement task list" in prompt
    assert "only result is knowledge" in prompt
    assert "implemented, reviewed, or fail independently" in prompt
    assert "without rereading the original goal or draft plan" in prompt


def test_planning_refine_uses_a_fresh_agent(tmp_path: Path, monkeypatch):
    import runner.core as core

    created = []
    calls = []

    class FakeAgent:
        def __init__(self, **kwargs):
            self.initial_session_id = kwargs["session_id"]
            self.session_id = kwargs["session_id"]
            created.append(self)

        def prepare_project(self):
            return []

    def task_payload(prefix: str):
        return {
            "tasks": [
                {
                    "title": f"{prefix} {index}",
                    "description": f"Create coherent result {index}",
                    "deliverable": f"Observable result {index}",
                    "acceptance_criteria": [
                        f"Result {index} is complete",
                        "Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior",
                    ],
                }
                for index in range(1, 7)
            ]
        }

    def fake_readonly_ask(agent, prompt, *args, **kwargs):
        calls.append((agent, prompt))
        agent.session_id = f"planning-session-{len(calls)}"
        payload = task_payload("Draft" if "Plan only" in prompt else "Refined")
        return json.dumps(payload), [], []

    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(
        backend="qwen",
        command="fake",
        agent_arg=[],
        planning_timeout=1,
        agent_idle_after_change_timeout=0,
        retry_wait=0,
        retry_max_wait=0,
    )
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"
    runner.work.mkdir()
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    runner.protected = []
    runner.agent = SimpleNamespace(session_id="")
    runner.ui = SimpleNamespace(set=lambda *args: None)
    runner._set_stage = lambda *args: None
    runner._save_state = lambda: None

    monkeypatch.setattr(core, "AgentClient", FakeAgent)
    monkeypatch.setattr(core, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()

    assert len(created) == 2
    assert created[0] is calls[0][0]
    assert created[1] is calls[1][0]
    assert created[0] is not created[1]
    assert [agent.initial_session_id for agent in created] == ["", ""]
    assert runner.state.tasks[0].title == "Refined 1"
