import json
from pathlib import Path
from types import SimpleNamespace

from runner.agent.prompts import (
    plan_finalize_prompt,
    plan_judge_prompt,
    plan_refine_prompt,
    plan_understand_prompt,
)
from runner.models import RunState, Task


def judge_payload(*, rejected_index: int | None = None, issue: str = "Task needs revision"):
    return {
        "accepted": rejected_index is None,
        "issues": [] if rejected_index is None else [f"Task {rejected_index}: {issue}"],
    }





class _StubAgent:
    def __init__(self, root: Path, session_id: str = ""):
        self.root = root
        self.session_id = session_id
        self.extra_args = []

    def set_extra_args(self, values):
        self.extra_args = list(values)

    def prepare_project(self):
        return []


def test_understanding_is_embedded_in_existing_prompts(tmp_path: Path):
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path), tasks=[Task(
        id="c01-t001",
        title="Implement result",
        description="Create the result",
        deliverable="result",
        acceptance_criteria=["result exists"],
    )])

    plan = plan_understand_prompt("g", tmp_path, state)
    from runner.agent.prompts import execution_prompt
    execute = execution_prompt(state, tmp_path, [])

    assert "dedicated project-understanding turn" in plan
    assert "Do not try to read the whole repository" in plan
    assert "inspect only the project files directly needed for this TODO" in execute
    assert not (Path(__file__).parents[1] / "prompts" / "understand.md").exists()

def test_planner_requires_self_contained_bounded_tasks(tmp_path: Path):
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    prompt = plan_finalize_prompt("g", tmp_path, state, same_session=True)

    assert "concrete observable project result" in prompt
    assert "local inspection needed for that task" in prompt
    assert "independently valuable observable result" in prompt
    assert "Return at least 1 ordered task(s)" in prompt
    assert "Keep an operation together with its required error handling and edge cases" in prompt
    assert "Do not create standalone inspection" in prompt
    assert "Never split work to target a task count" in prompt
    assert "Do not create umbrella TODOs" in prompt
    assert "Goal:" not in prompt
    assert "Project root:" not in prompt


def test_plan_refine_continues_existing_planner_contract(tmp_path: Path):
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    tasks = [Task(
        id="c01-t001",
        title="One result",
        description="Create one result",
        deliverable="result",
        acceptance_criteria=["result exists"],
    )]
    prompt = plan_refine_prompt("g", tmp_path, state, tasks)

    assert "Continue the existing planning work" in prompt
    assert "defend the old plan" in prompt
    assert "complete replacement task JSON" in prompt
    assert "do not repeat project-wide inspection" in prompt
    assert "do not implement or write files" in prompt


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

    assert "plan quality judge" in prompt
    assert "bounded read-only project inspection" in prompt
    assert "Do not rewrite the plan" in prompt
    assert "identify the affected task or plan-wide defect" in prompt
    assert '"accepted":false' in prompt
    assert '"accepted":true' in prompt
    assert 'FAIL:' in prompt
    assert 'PASS:' in prompt
    assert "process-only/read-only/check-only" in prompt
    assert "combines multiple independently valuable observable changes" in prompt
    assert "fragments one coherent behavior" in prompt
    assert "Standalone project-understanding/inspection work is invalid" in prompt




def test_plan_judge_and_refine_fresh_prompts_are_self_contained(tmp_path: Path):
    state = RunState(run_id="r", goal="UNIQUE GOAL", project_root=str(tmp_path))
    tasks = [Task(id="c01-t001", title="T", description="D", deliverable="X", acceptance_criteria=["A"])]
    judge = plan_judge_prompt("UNIQUE GOAL", tmp_path, state, tasks, same_session=False)
    refine = plan_refine_prompt("UNIQUE GOAL", tmp_path, state, tasks, judge_issues=["UNIQUE ISSUE"], same_session=False)
    assert "UNIQUE GOAL" in judge and '"title": "T"' in judge
    assert "UNIQUE GOAL" in refine and '"title": "T"' in refine and "UNIQUE ISSUE" in refine

def test_plan_judge_pass_skips_refine(tmp_path: Path, monkeypatch):
    import runner.core as core
    import runner.workflow.planning as planning

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
            payload = judge_payload()
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
    runner.agent = _StubAgent(tmp_path)
    runner.ui = SimpleNamespace(set=lambda *args: None)
    runner._set_stage = lambda *args: None
    runner._save_state = lambda: None

    monkeypatch.setattr(planning, "AgentClient", FakeAgent)
    monkeypatch.setattr(planning, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(planning, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()

    assert len(created) == 0
    assert all(agent is runner.agent for agent, _ in calls)
    assert runner.agent.root == tmp_path

    def excluded_tools(agent):
        return {
            agent.extra_args[index + 1]
            for index, value in enumerate(agent.extra_args[:-1])
            if value == "--exclude-tools"
        }

    assert "read_file" not in excluded_tools(runner.agent)
    assert "grep_search" not in excluded_tools(runner.agent)
    # Planning finished on the same agent and Core restored runtime capabilities.
    assert "write_file" not in excluded_tools(runner.agent)
    assert "run_shell_command" not in excluded_tools(runner.agent)
    assert "--yolo" in runner.agent.extra_args
    assert "--safe-mode" not in runner.agent.extra_args
    assert runner.state.tasks[0].title == "Draft 1"


def test_plan_judge_feedback_rewrites_with_original_planner(tmp_path: Path, monkeypatch):
    import runner.core as core
    import runner.workflow.planning as planning

    created = []
    prompts = []
    calls = []
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
        calls.append((agent, prompt))
        if "dedicated project-understanding turn" in prompt:
            agent.session_id = "planning-session"
            return "Relevant project evidence gathered", [], []
        if "plan quality judge" in prompt:
            judge_calls += 1
            payload = (
                judge_payload(rejected_index=1, issue="Split the compound deliverable")
                if judge_calls == 1
                else judge_payload()
            )
        elif "Plan judge issues" in prompt:
            payload = task_payload("Corrected")
        elif "Continue the existing planning work" in prompt:
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
    runner.agent = _StubAgent(tmp_path)
    runner.ui = SimpleNamespace(set=lambda *args: None)
    runner._set_stage = lambda *args: None
    runner._save_state = lambda: None

    monkeypatch.setattr(planning, "AgentClient", FakeAgent)
    monkeypatch.setattr(planning, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(planning, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()

    assert len(created) == 0
    assert judge_calls == 2
    assert all(agent is runner.agent for agent, _ in calls)
    assert any("Split the compound deliverable" in prompt for prompt in prompts)
    assert runner.state.tasks[0].title == "Refined 1"


def test_parse_plan_judgment_contract():
    import pytest

    from runner.agent.results import parse_plan_judgment
    from runner.errors import RunnerError

    assert parse_plan_judgment(json.dumps({"accepted": True, "issues": []}))["accepted"] is True
    rejected = parse_plan_judgment(
        json.dumps(judge_payload(rejected_index=2, issue="Split task 2"))
    )
    assert rejected["issues"] == ["Task 2: Split task 2"]
    with pytest.raises(RunnerError, match="accepted must be boolean"):
        parse_plan_judgment(json.dumps({"issues": []}))


def test_plan_judge_gate_rejects_task_and_plan_failures():
    from runner.agent.results import parse_plan_judgment

    payload = {
        "accepted": False,
        "issues": [
            "Task 1: No concrete deliverable",
            "A prerequisite appears after dependent work",
        ],
    }
    result = parse_plan_judgment(json.dumps(payload))
    assert result["accepted"] is False
    assert result["issues"] == payload["issues"]


def test_plan_judge_rejects_twice_then_defers_to_validator_loop(tmp_path: Path, monkeypatch):
    import runner.core as core
    import runner.workflow.planning as planning

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
            judge_payload(rejected_index=1, issue="Plan is still not bounded")
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
    runner.agent = _StubAgent(tmp_path)
    runner.ui = SimpleNamespace(set=lambda *args: None)
    runner._set_stage = lambda *args: None
    runner._save_state = lambda: None

    monkeypatch.setattr(planning, "AgentClient", FakeAgent)
    monkeypatch.setattr(planning, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(planning, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()

    assert len(created) == 0
    assert len(runner.state.tasks) == 6


def test_repair_plan_replaces_previous_cycle_tasks(tmp_path: Path, monkeypatch):
    import runner.core as core
    import runner.workflow.planning as planning

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
    runner.agent = _StubAgent(tmp_path)
    runner.ui = SimpleNamespace(set=lambda *args: None)
    runner._set_stage = lambda *args: None
    runner._save_state = lambda: None

    monkeypatch.setattr(planning, "AgentClient", FakeAgent)
    monkeypatch.setattr(planning, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(planning, "retry_model_call", lambda action, *args, **kwargs: action())
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
    runner.agent = _StubAgent(tmp_path)
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
    import runner.workflow.planning as planning
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
        if "Continue the existing planning work" in prompt:
            return json.dumps(_six_tasks("Refined")), [], []
        return json.dumps(judge_payload()), [], []

    runner = _adaptive_runner(core, tmp_path)
    monkeypatch.setattr(planning, "AgentClient", FakeAgent)
    monkeypatch.setattr(planning, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(planning, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()

    assert created == []
    assert runner.agent.root == tmp_path
    # Same-session finalize reuses the exact planner client/tool policy from Understand.
    excluded = {
        runner.agent.extra_args[i + 1]
        for i, value in enumerate(runner.agent.extra_args[:-1])
        if value == "--exclude-tools"
    }
    assert "read_file" not in excluded
    assert "grep_search" not in excluded
    assert runner.state.tasks[0].title == "Finalized 1"


def test_same_session_plan_failure_falls_back_to_fresh_no_tool_plan_without_reexplore(tmp_path: Path, monkeypatch):
    import runner.core as core
    import runner.workflow.planning as planning
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
        if "Continue the existing planning work" in prompt:
            return json.dumps(_six_tasks("Refined")), [], []
        return json.dumps(judge_payload()), [], []

    runner = _adaptive_runner(core, tmp_path)
    monkeypatch.setattr(planning, "AgentClient", FakeAgent)
    monkeypatch.setattr(planning, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(planning, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()

    assert explore_calls == 1
    assert created == []
    minimal = runner.agent
    assert minimal.root == tmp_path
    excluded = {
        minimal.extra_args[i + 1]
        for i, value in enumerate(minimal.extra_args[:-1])
        if value == "--exclude-tools"
    }
    assert "read_file" not in excluded
    assert "grep_search" not in excluded


def test_successful_understanding_without_session_is_carried_into_minimal_plan(tmp_path: Path, monkeypatch):
    import runner.core as core
    import runner.workflow.planning as planning

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
        if "Continue the existing planning work" in prompt:
            return json.dumps(_six_tasks("Refined")), [], []
        return json.dumps(judge_payload()), [], []

    runner = _adaptive_runner(core, tmp_path)
    monkeypatch.setattr(planning, "AgentClient", FakeAgent)
    monkeypatch.setattr(planning, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(planning, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()
    assert runner.state.tasks[0].title == "Minimal 1"


def test_refiner_error_keeps_last_valid_plan(tmp_path: Path, monkeypatch):
    import runner.core as core
    import runner.workflow.planning as planning
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
        if "Continue the existing planning work" in prompt:
            raise RunnerError("refiner unavailable")
        return json.dumps(judge_payload()), [], []

    runner = _adaptive_runner(core, tmp_path)
    monkeypatch.setattr(planning, "AgentClient", FakeAgent)
    monkeypatch.setattr(planning, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(planning, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()
    assert runner.state.tasks[0].title == "Draft 1"


def test_judge_error_uses_last_valid_plan(tmp_path: Path, monkeypatch):
    import runner.core as core
    import runner.workflow.planning as planning
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
        if "Continue the existing planning work" in prompt:
            return json.dumps(_six_tasks("Refined")), [], []
        raise RunnerError("judge unavailable")

    runner = _adaptive_runner(core, tmp_path)
    monkeypatch.setattr(planning, "AgentClient", FakeAgent)
    monkeypatch.setattr(planning, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(planning, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()
    assert runner.state.tasks[0].title == "Draft 1"


def test_same_session_finalize_is_compact_but_fresh_fallback_is_self_contained(tmp_path: Path):
    state = RunState(run_id="r", goal="UNIQUE ORIGINAL GOAL", project_root=str(tmp_path))
    (tmp_path / "app.txt").write_text("x", encoding="utf-8")

    same = plan_finalize_prompt("UNIQUE ORIGINAL GOAL", tmp_path, state, same_session=True)
    fresh = plan_finalize_prompt(
        "UNIQUE ORIGINAL GOAL",
        tmp_path,
        state,
        same_session=False,
        inspection_summary="UNIQUE INSPECTION SUMMARY",
    )

    assert "UNIQUE ORIGINAL GOAL" not in same
    assert str(tmp_path) not in same
    assert "app.txt" not in same
    assert "UNIQUE ORIGINAL GOAL" in fresh
    assert str(tmp_path) in fresh
    assert "app.txt" not in fresh
    assert "UNIQUE INSPECTION SUMMARY" in fresh
    assert len(same) < len(fresh)

def test_rewrite_retries_fresh_only_after_planner_session_is_lost(tmp_path: Path, monkeypatch):
    import runner.core as core
    import runner.workflow.planning as planning
    from runner.errors import RunnerError

    created = []
    calls = []
    judge_calls = 0
    rewrite_calls = 0

    class FakeAgent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]
            created.append(self)
        def prepare_project(self):
            return []

    def fake_readonly_ask(agent, prompt, *args, **kwargs):
        nonlocal judge_calls, rewrite_calls
        calls.append((agent, prompt))
        if "dedicated project-understanding turn" in prompt:
            agent.session_id = "planner-session"
            return "evidence", [], []
        if "Create the implementation plan now" in prompt:
            return json.dumps(_six_tasks("Draft")), [], []
        if "plan quality judge" in prompt:
            judge_calls += 1
            return json.dumps(judge_payload(rejected_index=1)) if judge_calls == 1 else json.dumps(judge_payload()), [], []
        if "Continue the existing planning work" in prompt:
            rewrite_calls += 1
            if rewrite_calls == 1:
                agent.session_id = ""
                raise RunnerError("session unavailable")
            agent.session_id = "fresh-planner-session"
            return json.dumps(_six_tasks("Recovered")), [], []
        raise AssertionError(prompt)

    runner = _adaptive_runner(core, tmp_path)
    monkeypatch.setattr(planning, "AgentClient", FakeAgent)
    monkeypatch.setattr(planning, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(planning, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()

    rewrite_agents = [agent for agent, prompt in calls if "Continue the existing planning work" in prompt]
    assert rewrite_calls == 2
    assert rewrite_agents == [runner.agent, runner.agent]
    assert runner.state.tasks[0].title == "Recovered 1"


def test_planning_reuses_existing_main_session_when_available(tmp_path: Path, monkeypatch):
    import runner.core as core
    import runner.workflow.planning as planning

    created = []

    class FakeAgent:
        def __init__(self, **kwargs):
            self.initial_session_id = kwargs["session_id"]
            self.session_id = kwargs["session_id"]
            created.append(self)
        def prepare_project(self):
            return []

    def fake_readonly_ask(agent, prompt, *args, **kwargs):
        if "dedicated project-understanding turn" in prompt:
            assert agent.session_id == "executor-session"
            return "evidence", [], []
        if "Create the implementation plan now" in prompt:
            return json.dumps(_six_tasks("Plan")), [], []
        return json.dumps(judge_payload()), [], []

    runner = _adaptive_runner(core, tmp_path)
    runner.agent.session_id = "executor-session"
    monkeypatch.setattr(planning, "AgentClient", FakeAgent)
    monkeypatch.setattr(planning, "readonly_ask", fake_readonly_ask)
    monkeypatch.setattr(planning, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()

    assert created == []
    assert runner.agent.session_id == "executor-session"


def test_planning_switches_main_agent_args_then_restores_runtime(tmp_path: Path, monkeypatch):
    import runner.core as core

    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(
        backend="qwen", command="fake", agent_arg=[], planning_timeout=1,
        agent_idle_after_change_timeout=0, retry_wait=0, retry_max_wait=0,
    )
    runner.root = tmp_path
    runner.work = tmp_path / ".ai-task-runner"; runner.work.mkdir()
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    runner.protected = []
    runner.agent = _StubAgent(tmp_path)
    runner.ui = SimpleNamespace(set=lambda *args: None)
    runner._set_stage = lambda *args: None
    runner._save_state = lambda: None
    seen = []

    def fake_build_plan(*args, **kwargs):
        seen.append(list(runner.agent.extra_args))
        runner.agent.session_id = "planning-session"
        return [Task(id="c01-t001", title="T", description="D", deliverable="X", acceptance_criteria=["A"])]

    monkeypatch.setattr(core, "build_plan", fake_build_plan)
    monkeypatch.setattr(core, "retry_model_call", lambda action, *args, **kwargs: action())
    monkeypatch.setattr(core, "show_todo", lambda *args, **kwargs: None)

    runner._plan_if_needed()

    assert seen and "--yolo" in seen[0] and "--safe-mode" in seen[0]
    assert "--exclude-tools" in seen[0]
    assert runner.agent.session_id == "planning-session"
    assert "--yolo" in runner.agent.extra_args
    assert "--safe-mode" not in runner.agent.extra_args


def test_repair_planning_is_reanchored_to_original_goal(tmp_path: Path):
    state = RunState(
        run_id="r",
        goal="ORIGINAL GOAL",
        project_root=str(tmp_path),
        cycle=2,
        validator_output="LATEST VALIDATOR FAILURE",
    )
    understand = plan_understand_prompt("ORIGINAL GOAL", tmp_path, state)
    finalize_same = plan_finalize_prompt(
        "ORIGINAL GOAL", tmp_path, state, same_session=True
    )
    finalize_fresh = plan_finalize_prompt(
        "ORIGINAL GOAL", tmp_path, state, same_session=False
    )

    for prompt in (understand, finalize_same, finalize_fresh):
        assert "original goal" in prompt.lower()
        assert "existing implementation" in prompt.lower()
        assert "evidence" in prompt.lower()
        assert "merely because it already exists" in prompt.lower()
        assert "smallest repair" in prompt.lower()

    assert "LATEST VALIDATOR FAILURE" in understand
    assert "LATEST VALIDATOR FAILURE" in finalize_fresh


def test_repair_judge_and_refine_reject_existing_design_as_specification(tmp_path: Path):
    state = RunState(
        run_id="r",
        goal="ORIGINAL GOAL",
        project_root=str(tmp_path),
        cycle=2,
        validator_output="LATEST VALIDATOR FAILURE",
    )
    tasks = [Task(
        id="c02-t001",
        title="Repair result",
        description="Repair the result",
        deliverable="result",
        acceptance_criteria=["result is correct"],
    )]

    judge = plan_judge_prompt("ORIGINAL GOAL", tmp_path, state, tasks)
    refine = plan_refine_prompt(
        "ORIGINAL GOAL", tmp_path, state, tasks, judge_issues=["wrong direction"]
    )
    judge_fresh = plan_judge_prompt(
        "ORIGINAL GOAL", tmp_path, state, tasks, same_session=False
    )
    refine_fresh = plan_refine_prompt(
        "ORIGINAL GOAL", tmp_path, state, tasks,
        judge_issues=["wrong direction"], same_session=False
    )

    for prompt in (judge, refine, judge_fresh, refine_fresh):
        assert "original goal" in prompt.lower()
        assert "existing" in prompt.lower()
        assert "merely because it already exists" in prompt.lower()


def test_repair_planning_partitions_failures_by_todo(tmp_path: Path):
    state = RunState(
        run_id="r",
        goal="ORIGINAL GOAL",
        project_root=str(tmp_path),
        cycle=2,
        validator_output="E001 unrelated\nE005 current",
    )
    tasks = [Task(
        id="c02-t001",
        title="Current repair",
        description="Repair current behavior",
        deliverable="result",
        acceptance_criteria=["current result is correct"],
    )]

    prompts = [
        plan_understand_prompt("ORIGINAL GOAL", tmp_path, state),
        plan_finalize_prompt("ORIGINAL GOAL", tmp_path, state, same_session=True),
        plan_finalize_prompt("ORIGINAL GOAL", tmp_path, state, same_session=False),
        plan_judge_prompt("ORIGINAL GOAL", tmp_path, state, tasks),
        plan_judge_prompt("ORIGINAL GOAL", tmp_path, state, tasks, same_session=False),
        plan_refine_prompt("ORIGINAL GOAL", tmp_path, state, tasks, judge_issues=["split failures"]),
        plan_refine_prompt(
            "ORIGINAL GOAL", tmp_path, state, tasks,
            judge_issues=["split failures"], same_session=False,
        ),
    ]

    for prompt in prompts:
        lower = prompt.lower()
        assert "relevant" in lower
        assert "acceptance criteria" in lower
        assert "later-todo" in lower
        assert "unrelated" in lower


def test_planning_excludes_runner_owned_validation_and_merges_shared_repair_causes(tmp_path: Path):
    state = RunState(
        run_id="r",
        goal="ORIGINAL GOAL",
        project_root=str(tmp_path),
        cycle=2,
        validator_output="failure one\nfailure two",
    )
    tasks = [Task(
        id="c02-t001",
        title="Repair",
        description="Repair shared behavior",
        deliverable="result",
        acceptance_criteria=["result is correct"],
    )]
    prompts = [
        plan_finalize_prompt("ORIGINAL GOAL", tmp_path, state, same_session=True),
        plan_finalize_prompt("ORIGINAL GOAL", tmp_path, state, same_session=False),
        plan_judge_prompt("ORIGINAL GOAL", tmp_path, state, tasks),
        plan_judge_prompt("ORIGINAL GOAL", tmp_path, state, tasks, same_session=False),
        plan_refine_prompt("ORIGINAL GOAL", tmp_path, state, tasks, judge_issues=["repair"], same_session=True),
        plan_refine_prompt("ORIGINAL GOAL", tmp_path, state, tasks, judge_issues=["repair"], same_session=False),
    ]
    for prompt in prompts:
        lower = prompt.lower()
        assert "final validation" in lower and "runner" in lower
        assert "underlying contract or root cause" in lower
