from pathlib import Path
from types import SimpleNamespace
import json

from runner.models import RunState, Task
from runner.prompting import plan_judge_prompt, plan_prompt, plan_refine_prompt


def judge_payload(task_count: int, *, rejected_index: int | None = None, issue: str = "Task needs revision"):
    checks = [
        {
            "index": index,
            "produces_change": index != rejected_index,
            "properly_sized": index != rejected_index,
            "verifiable": index != rejected_index,
            "issues": [issue] if index == rejected_index else [],
        }
        for index in range(1, task_count + 1)
    ]
    return {
        "task_checks": checks,
        "coverage_complete": True,
        "dependency_order_ok": True,
        "no_overlap": True,
        "plan_issues": [],
    }




def test_understanding_is_embedded_in_existing_prompts(tmp_path: Path):
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path), tasks=[Task(
        id="c01-t001",
        title="Implement result",
        description="Create the result",
        deliverable="result",
        acceptance_criteria=["result exists"],
    )])

    plan = plan_prompt("g", tmp_path, state, [])
    from runner.prompting import execution_prompt
    execute = execution_prompt(state, tmp_path, [])

    assert "bounded read-only inspection at the start of the concrete TODO" in plan
    assert "This inspection is preparation inside the TODO and never completes the TODO by itself" in execute
    assert not (Path(__file__).parents[1] / "prompts" / "understand.md").exists()

def test_planner_requires_self_contained_bounded_tasks(tmp_path: Path):
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    prompt = plan_prompt("g", tmp_path, state, [])

    assert "concrete, observable project result" in prompt
    assert "execution does not need the original goal or planning output" in prompt
    assert "objective stopping evidence" in prompt
    assert "Return at least 6 ordered task(s)" in prompt
    assert "Multiple TODOs may modify the same file" in prompt


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
    assert "Knowledge, findings" in prompt
    assert "implemented, reviewed, verified, retried, or fail independently" in prompt
    assert "never use file count as the task boundary" in prompt
    assert "without rereading the original goal or draft plan" in prompt


def test_plan_judge_is_semantic_and_read_only(tmp_path: Path):
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    tasks = [Task(
        id="c01-t001",
        title="One result",
        description="Create one result",
        deliverable="result",
        acceptance_criteria=["result exists"],
    )]
    prompt = plan_judge_prompt("g", tmp_path, state, tasks)

    assert "independent plan quality judge" in prompt
    assert "Do not rewrite the plan" in prompt
    assert "Never judge from title wording or keyword matching" in prompt
    assert '"accepted":true' in prompt
    assert 'multiple TODOs may modify the same file' in prompt


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
        if "plan quality judge" in prompt:
            payload = judge_payload(6)
        else:
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

    assert len(created) == 4
    assert created[0] is calls[0][0]
    assert created[1] is calls[1][0]
    assert created[2] is calls[2][0]
    assert created[3] is calls[3][0]
    assert len({id(agent) for agent in created}) == 4
    assert [agent.initial_session_id for agent in created] == ["", "", "", ""]
    assert runner.state.tasks[0].title == "Refined 1"


def test_plan_judge_feedback_drives_one_more_fresh_rewrite(tmp_path: Path, monkeypatch):
    import runner.core as core

    created = []
    prompts = []
    judge_calls = 0

    class FakeAgent:
        def __init__(self, **kwargs):
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
        nonlocal judge_calls
        prompts.append(prompt)
        if "plan quality judge" in prompt:
            judge_calls += 1
            payload = (
                judge_payload(6, rejected_index=1, issue="Split the compound deliverable")
                if judge_calls == 1
                else judge_payload(6)
            )
        elif "Plan judge issues" in prompt:
            payload = task_payload("Corrected")
        elif "independent plan editor" in prompt:
            payload = task_payload("Refined")
        else:
            payload = task_payload("Draft")
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

    assert len(created) == 6
    assert judge_calls == 3
    assert any("Split the compound deliverable" in prompt for prompt in prompts)
    assert runner.state.tasks[0].title == "Corrected 1"


def test_parse_plan_judgment_contract():
    import pytest
    from runner.errors import RunnerError
    from runner.support import parse_plan_judgment

    assert parse_plan_judgment(json.dumps({"accepted": True, "issues": []}), 2)["accepted"] is True
    assert parse_plan_judgment(json.dumps(judge_payload(2)), 2)["accepted"] is True
    rejected = parse_plan_judgment(
        json.dumps(judge_payload(2, rejected_index=2, issue="Split task 2")),
        2,
    )
    assert rejected["issues"] == ["Task 2: Split task 2"]
    with pytest.raises(RunnerError, match="accepted and issues"):
        parse_plan_judgment(json.dumps(judge_payload(1)), 2)
    invalid = judge_payload(2)
    invalid["task_checks"][1]["index"] = 1
    with pytest.raises(RunnerError, match="index is invalid"):
        parse_plan_judgment(json.dumps(invalid), 2)


def test_plan_judge_gate_rejects_task_and_plan_failures():
    from runner.support import parse_plan_judgment

    payload = judge_payload(8, rejected_index=1, issue="No concrete deliverable")
    payload["dependency_order_ok"] = False
    payload["plan_issues"] = ["A prerequisite appears after dependent work"]

    result = parse_plan_judgment(json.dumps(payload), 8)

    assert result["accepted"] is False
    assert "Task 1: No concrete deliverable" in result["issues"]
    assert "A prerequisite appears after dependent work" in result["issues"]


def test_plan_judge_rejects_twice_before_restarting_planning(tmp_path: Path, monkeypatch):
    import pytest
    import runner.core as core
    from runner.errors import RunnerError

    created = []

    class FakeAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]
            created.append(self)

        def prepare_project(self):
            return []

    tasks = {
        "tasks": [
            {
                "title": f"Result {index}",
                "description": f"Create result {index}",
                "deliverable": f"Result {index}",
                "acceptance_criteria": [f"Result {index} exists"],
            }
            for index in range(1, 7)
        ]
    }

    def fake_readonly_ask(agent, prompt, *args, **kwargs):
        payload = (
            judge_payload(6, rejected_index=1, issue="Plan is still not bounded")
            if "plan quality judge" in prompt
            else tasks
        )
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

    with pytest.raises(RunnerError, match="plan judge rejected"):
        runner._plan_if_needed()

    assert len(created) == 5
