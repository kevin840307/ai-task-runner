from pathlib import Path
from types import SimpleNamespace
import json

from runner.models import RunState, Task
from runner.prompting import plan_finalize_prompt, plan_judge_prompt, plan_prompt, plan_refine_prompt


def judge_payload(task_count: int, *, rejected_index: int | None = None, issue: str = "Task needs revision"):
    del task_count
    return {
        "accepted": rejected_index is None,
        "issues": [] if rejected_index is None else [f"Task {rejected_index}: {issue}"],
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

    assert "dedicated project-understanding turn" in plan
    assert "Do not try to read the whole repository" in plan
    assert "This inspection is preparation inside the TODO and never completes the TODO by itself" in execute
    assert not (Path(__file__).parents[1] / "prompts" / "understand.md").exists()

def test_planner_requires_self_contained_bounded_tasks(tmp_path: Path):
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    prompt = plan_finalize_prompt("g", tmp_path, state, same_session=True)

    assert "concrete observable project result" in prompt
    assert "local inspection needed for that task" in prompt
    assert "real deliverables" in prompt
    assert "Return at least 6 ordered task(s)" in prompt
    assert "Split independently implementable or verifiable changes" in prompt
    assert "Do not create standalone inspection" in prompt
    assert "never manufacture preparation/read/check tasks" in prompt


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
    assert "dedicated planning turn before TODO creation" in prompt
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
    assert "could be completed entirely by reading, reasoning, deciding, reviewing, or checking" in prompt
    assert "dedicated planning turn before TODO creation" in prompt
    assert "Never judge from title wording or keyword matching" in prompt


def test_planning_refine_uses_a_fresh_agent(tmp_path: Path, monkeypatch):
    import runner.core as core

    created = []
    calls = []

    class FakeAgent:
        def __init__(self, **kwargs):
            self.initial_session_id = kwargs["session_id"]
            self.session_id = kwargs["session_id"]
            self.root = kwargs["root"]
            self.extra_args = kwargs["extra_args"]
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
        if "dedicated project-understanding turn" in prompt:
            agent.session_id = "planning-session"
            return "Relevant project evidence gathered", [], []
        if "plan quality judge" in prompt:
            payload = judge_payload(6)
        elif "Create the implementation plan now" in prompt:
            payload = task_payload("Draft")
        else:
            payload = task_payload("Refined")
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
    assert [agent.initial_session_id for agent in created] == ["", "planning-session", "", ""]
    assert created[0].root == tmp_path
    assert created[1].root == tmp_path
    assert created[2].root == runner.work
    assert created[3].root == runner.work

    def excluded_tools(agent):
        return {
            agent.extra_args[index + 1]
            for index, value in enumerate(agent.extra_args[:-1])
            if value == "--exclude-tools"
        }

    assert "read_file" not in excluded_tools(created[0])
    assert "grep_search" not in excluded_tools(created[0])
    assert "write_file" in excluded_tools(created[0])
    assert "run_shell_command" in excluded_tools(created[0])
    assert "read_file" in excluded_tools(created[1])
    assert "read_file" in excluded_tools(created[2])
    assert "read_file" in excluded_tools(created[3])
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
        if "dedicated project-understanding turn" in prompt:
            agent.session_id = "planning-session"
            return "Relevant project evidence gathered", [], []
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
        elif "Create the implementation plan now" in prompt:
            payload = task_payload("Draft")
        else:
            raise AssertionError(prompt)
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
    assert judge_calls == 2
    assert any("Split the compound deliverable" in prompt for prompt in prompts)
    assert runner.state.tasks[0].title == "Corrected 1"


def test_parse_plan_judgment_contract():
    import pytest
    from runner.errors import RunnerError
    from runner.support import parse_plan_judgment

    assert parse_plan_judgment(json.dumps({"accepted": True, "issues": []}), 2)["accepted"] is True
    rejected = parse_plan_judgment(
        json.dumps(judge_payload(2, rejected_index=2, issue="Split task 2")),
        2,
    )
    assert rejected["issues"] == ["Task 2: Split task 2"]
    with pytest.raises(RunnerError, match="accepted must be boolean"):
        parse_plan_judgment(json.dumps({"issues": []}), 2)


def test_plan_judge_gate_rejects_task_and_plan_failures():
    from runner.support import parse_plan_judgment

    payload = {
        "accepted": False,
        "issues": [
            "Task 1: No concrete deliverable",
            "A prerequisite appears after dependent work",
        ],
    }
    result = parse_plan_judgment(json.dumps(payload), 8)
    assert result["accepted"] is False
    assert result["issues"] == payload["issues"]


def test_plan_judge_rejects_twice_then_defers_to_validator_loop(tmp_path: Path, monkeypatch):
    import runner.core as core

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
        if "dedicated project-understanding turn" in prompt:
            agent.session_id = "planning-session"
            return "Relevant project evidence gathered", [], []
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

    runner._plan_if_needed()

    assert len(created) == 6
    assert len(runner.state.tasks) == 6


def test_repair_plan_replaces_previous_cycle_tasks(tmp_path: Path, monkeypatch):
    import runner.core as core

    class FakeAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]

        def prepare_project(self):
            return []

    def fake_readonly_ask(agent, prompt, *args, **kwargs):
        if "dedicated project-understanding turn" in prompt:
            agent.session_id = "planning-session"
            return "Relevant repair evidence gathered", [], []
        if "plan quality judge" in prompt:
            payload = {"accepted": True, "issues": []}
        else:
            payload = {"tasks": [{
                "title": "Repair current failure",
                "description": "Repair the validator-reported failure",
                "deliverable": "Validator-relevant repair",
                "acceptance_criteria": ["The reported failure is fixed"],
            }]}
        return json.dumps(payload), [], []

    old = Task(
        id="c01-t001",
        title="Old completed task",
        description="Old work",
        deliverable="Old result",
        acceptance_criteria=["Old result exists"],
        status="completed",
    )
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
    runner.state = RunState(
        run_id="r",
        goal="g",
        project_root=str(tmp_path),
        cycle=2,
        current=1,
        tasks=[old],
        stage="validator_failed",
        validator_output="failure",
    )
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

    assert runner.state.current == 0
    assert [task.id for task in runner.state.tasks] == ["c02-t001"]
    assert [task.title for task in runner.state.tasks] == ["Repair current failure"]


def _adaptive_runner(core, tmp_path):
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
    runner.work.mkdir(exist_ok=True)
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    runner.protected = []
    runner.agent = SimpleNamespace(session_id="")
    runner.ui = SimpleNamespace(set=lambda *args: None)
    runner._set_stage = lambda *args: None
    runner._save_state = lambda: None
    return runner


def _six_tasks(prefix="Plan"):
    return {
        "tasks": [
            {
                "title": f"{prefix} {index}",
                "description": f"Create concrete result {index}",
                "deliverable": f"Observable result {index}",
                "acceptance_criteria": [
                    f"Result {index} is complete",
                    "Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior",
                ],
            }
            for index in range(1, 7)
        ]
    }


def test_understanding_failure_reuses_same_session_for_no_tool_plan(tmp_path: Path, monkeypatch):
    import runner.core as core
    from runner.errors import RunnerError

    created = []

    class FakeAgent:
        def __init__(self, **kwargs):
            self.initial_session_id = kwargs["session_id"]
            self.session_id = kwargs["session_id"]
            self.root = kwargs["root"]
            self.extra_args = kwargs["extra_args"]
            created.append(self)

        def prepare_project(self):
            return []

    def fake_readonly_ask(agent, prompt, *args, **kwargs):
        if "dedicated project-understanding turn" in prompt:
            agent.session_id = "draft-session"
            raise RunnerError("understanding exploration failed")
        if "Create the implementation plan now" in prompt:
            assert agent.session_id == "draft-session"
            return json.dumps(_six_tasks("Finalized")), [], []
        if "independent plan editor" in prompt:
            return json.dumps(_six_tasks("Refined")), [], []
        return json.dumps(judge_payload(6)), [], []

    runner = _adaptive_runner(core, tmp_path)
    monkeypatch.setattr(core, "AgentClient", FakeAgent)
    monkeypatch.setattr(core, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()

    assert [agent.initial_session_id for agent in created] == ["", "draft-session", "", ""]
    assert created[0].root == tmp_path
    assert created[1].root == tmp_path
    excluded = {
        created[1].extra_args[i + 1]
        for i, value in enumerate(created[1].extra_args[:-1])
        if value == "--exclude-tools"
    }
    assert "read_file" in excluded
    assert "grep_search" in excluded
    assert runner.state.tasks[0].title == "Refined 1"


def test_same_session_plan_failure_falls_back_to_fresh_no_tool_plan_without_reexplore(tmp_path: Path, monkeypatch):
    import runner.core as core
    from runner.errors import RunnerError

    created = []
    explore_calls = 0

    class FakeAgent:
        def __init__(self, **kwargs):
            self.initial_session_id = kwargs["session_id"]
            self.session_id = kwargs["session_id"]
            self.root = kwargs["root"]
            self.extra_args = kwargs["extra_args"]
            created.append(self)

        def prepare_project(self):
            return []

    def fake_readonly_ask(agent, prompt, *args, **kwargs):
        nonlocal explore_calls
        if "dedicated project-understanding turn" in prompt:
            explore_calls += 1
            agent.session_id = "draft-session"
            raise RunnerError("draft exploration failed")
        if "Create the implementation plan now" in prompt and agent.session_id:
            raise RunnerError("resume failed")
        if "Create the implementation plan now" in prompt:
            return json.dumps(_six_tasks("Minimal")), [], []
        if "independent plan editor" in prompt:
            return json.dumps(_six_tasks("Refined")), [], []
        return json.dumps(judge_payload(6)), [], []

    runner = _adaptive_runner(core, tmp_path)
    monkeypatch.setattr(core, "AgentClient", FakeAgent)
    monkeypatch.setattr(core, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()

    assert explore_calls == 1
    assert created[0].root == tmp_path
    assert created[1].initial_session_id == "draft-session"
    minimal = created[2]
    assert minimal.initial_session_id == ""
    assert minimal.root == runner.work
    excluded = {
        minimal.extra_args[i + 1]
        for i, value in enumerate(minimal.extra_args[:-1])
        if value == "--exclude-tools"
    }
    assert "read_file" in excluded
    assert "grep_search" in excluded


def test_successful_understanding_without_session_is_carried_into_minimal_plan(tmp_path: Path, monkeypatch):
    import runner.core as core

    prompts = []

    class FakeAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]
        def prepare_project(self):
            return []

    def fake_readonly_ask(agent, prompt, *args, **kwargs):
        prompts.append(prompt)
        if "dedicated project-understanding turn" in prompt:
            return "Important evidence: renderer uses layered values and Jinja templates.", [], []
        if "Create the implementation plan now" in prompt:
            assert "Important evidence: renderer uses layered values and Jinja templates." in prompt
            return json.dumps(_six_tasks("Minimal")), [], []
        if "independent plan editor" in prompt:
            return json.dumps(_six_tasks("Refined")), [], []
        return json.dumps(judge_payload(6)), [], []

    runner = _adaptive_runner(core, tmp_path)
    monkeypatch.setattr(core, "AgentClient", FakeAgent)
    monkeypatch.setattr(core, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()
    assert runner.state.tasks[0].title == "Refined 1"


def test_refiner_error_keeps_last_valid_plan(tmp_path: Path, monkeypatch):
    import runner.core as core
    from runner.errors import RunnerError

    class FakeAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]
        def prepare_project(self):
            return []

    def fake_readonly_ask(agent, prompt, *args, **kwargs):
        if "dedicated project-understanding turn" in prompt:
            agent.session_id = "draft-session"
            return "Relevant project evidence gathered", [], []
        if "Create the implementation plan now" in prompt:
            return json.dumps(_six_tasks("Draft")), [], []
        if "independent plan editor" in prompt:
            raise RunnerError("refiner unavailable")
        return json.dumps(judge_payload(6)), [], []

    runner = _adaptive_runner(core, tmp_path)
    monkeypatch.setattr(core, "AgentClient", FakeAgent)
    monkeypatch.setattr(core, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()
    assert runner.state.tasks[0].title == "Draft 1"


def test_judge_error_uses_last_valid_refined_plan(tmp_path: Path, monkeypatch):
    import runner.core as core
    from runner.errors import RunnerError

    class FakeAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]
        def prepare_project(self):
            return []

    def fake_readonly_ask(agent, prompt, *args, **kwargs):
        if "dedicated project-understanding turn" in prompt:
            agent.session_id = "draft-session"
            return "Relevant project evidence gathered", [], []
        if "Create the implementation plan now" in prompt:
            return json.dumps(_six_tasks("Draft")), [], []
        if "independent plan editor" in prompt:
            return json.dumps(_six_tasks("Refined")), [], []
        raise RunnerError("judge unavailable")

    runner = _adaptive_runner(core, tmp_path)
    monkeypatch.setattr(core, "AgentClient", FakeAgent)
    monkeypatch.setattr(core, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()
    assert runner.state.tasks[0].title == "Refined 1"
