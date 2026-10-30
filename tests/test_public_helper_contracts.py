from pathlib import Path
from types import SimpleNamespace

import pytest

import runner.agent.backend as backend_module
import runner.agent.qwen as qwen
from runner.agent.backend import BaseBackend, configure_sandbox_args
from runner.agent.client import build_backend_args, configure_ai_client
from runner.agent.structured import (
    json_candidates,
    parse_result,
    require_object,
    require_text,
    require_text_list,
)
from runner.api import RunRequest
from runner.bootstrap import register_resources, runtime_scope
from runner.config.runtime import RuntimeConfig
from runner.errors import (
    ConfigurationError,
    RunnerError,
    backend_diagnostic_parts,
    diagnostic_detail,
    diagnostic_error,
    is_transient_error,
)
from runner.runtime.run_state import RunState, Task
from runner.workflow.contracts import StageContext, StageResult
from runner.workflow.dynamic_expansion import activate_dynamic_task, dynamic_done_target
from runner.workflow.flow_engine import (
    FlowEngine,
    build_flow_engine,
    resolve_handoff_target,
    resolve_stage_target,
)
from runner.workflow.loader import normalize_workflow
from runner.workflow.results import finish_run


def test_structured_public_helpers_cover_embedded_json_and_schema_failures():
    values = list(json_candidates('prefix {"bad": 1} middle {"ok": "yes"} suffix'))
    assert values == [{"bad": 1}, {"ok": "yes"}]

    def parser(value):
        obj = require_object(value)
        if "ok" not in obj:
            raise RunnerError("missing ok")
        return require_text(obj["ok"], "ok")

    assert parse_result('{"bad": 1}\n{"ok": " yes "}', parser) == "yes"

    with pytest.raises(RunnerError, match="missing ok"):
        parse_result('{"bad": 1}', parser)
    with pytest.raises(RunnerError, match="no valid JSON"):
        parse_result("not-json", parser)

    assert require_object({"x": 1}) == {"x": 1}
    assert require_text("  value  ", "field") == "value"
    assert require_text_list([" a ", "b"], "items", allow_empty=False) == ["a", "b"]

    with pytest.raises(RunnerError, match="must be an object"):
        require_object([])
    with pytest.raises(RunnerError, match="field must be a non-empty string"):
        require_text(" ", "field")
    with pytest.raises(RunnerError, match="items must be an array"):
        require_text_list("bad", "items")
    with pytest.raises(RunnerError, match="items must not be empty"):
        require_text_list([], "items", allow_empty=False)


def test_backend_session_helpers_find_nested_session_and_source_event():
    events = [
        {"type": "progress", "payload": {"value": 1}},
        {"type": "result", "payload": [{"meta": {"sessionId": "session-42"}}]},
    ]

    assert BaseBackend.find_session_id(events) == "session-42"
    assert BaseBackend.find_session_source_event(events) == "event[1]:result"
    assert BaseBackend.find_session_id([{"type": "progress"}]) == ""
    assert BaseBackend.find_session_source_event([{"type": "progress"}]) == "-"


def test_configure_sandbox_args_is_copying_idempotent_and_backend_owned(monkeypatch):
    fake_backend = SimpleNamespace(sandbox_flags=("--fake-sandbox",))
    monkeypatch.setattr(backend_module, "_backend_type", lambda _name: fake_backend)

    original = ["--existing"]
    assert configure_sandbox_args("fake", original, sandbox=False) == ["--existing"]
    assert configure_sandbox_args("fake", original, sandbox=True) == [
        "--existing",
        "--fake-sandbox",
    ]
    assert configure_sandbox_args(
        "fake", ["--fake-sandbox"], sandbox=True
    ) == ["--fake-sandbox"]
    assert original == ["--existing"]


def test_qwen_public_argument_helpers_are_idempotent_and_preserve_compat_tool():
    compat = qwen.QWEN_NO_TOOL_COMPAT_TOOL
    args = [
        f"--exclude-tools={compat}",
        "--exclude-tools",
        compat,
        "--approval-mode",
        "default",
    ]
    qwen.ensure_qwen_compat_tool(args)
    assert f"--exclude-tools={compat}" not in args
    assert not any(
        args[index] == "--exclude-tools" and args[index + 1] == compat
        for index in range(len(args) - 1)
    )

    qwen.ensure_qwen_yolo(args)
    assert "--yolo" not in args

    qwen.ensure_qwen_safe_mode(args)
    qwen.ensure_qwen_safe_mode(args)
    assert args.count("--safe-mode") == 1

    qwen.ensure_qwen_max_tool_calls(args, "9")
    qwen.ensure_qwen_max_tool_calls(args, "99")
    index = args.index("--max-tool-calls")
    assert args[index + 1] == "9"
    assert args.count("--max-tool-calls") == 1

    qwen.exclude_qwen_tools(args, ("edit", "edit"))
    assert args.count("edit") == 1

    project_read = set(qwen.QWEN_PLANNING_PROJECT_READ_TOOLS)
    assert project_read.isdisjoint(
        qwen.qwen_readonly_excluded_tools(allow_project_read=True)
    )

    planning = qwen.configure_qwen_args(
        "planning",
        [],
        allow_project_read=False,
    )
    assert "--yolo" in planning
    assert "--safe-mode" in planning
    assert compat not in [
        planning[index + 1]
        for index, value in enumerate(planning[:-1])
        if value == "--exclude-tools"
    ]


def test_build_and_configure_ai_client_public_helpers_apply_runtime_policy():
    config = SimpleNamespace(
        backend="qwen",
        agent_args=[],
        sandbox=False,
    )
    args = build_backend_args(config, "planning", allow_project_read=False)
    assert "--safe-mode" in args

    class Client:
        def __init__(self):
            self.args = None
            self.runtime = None

        def set_extra_args(self, values):
            self.args = list(values)

        def set_runtime(self, mode, **kwargs):
            self.runtime = (mode, kwargs)

    client = Client()
    configure_ai_client(
        client,
        config,
        "review",
        allow_project_read=True,
    )
    assert client.args
    assert client.runtime == (
        "review",
        {"allow_project_read": True, "sandbox": False},
    )


def test_error_chain_helpers_preserve_transient_and_backend_diagnostics():
    class BackendFailure(RunnerError):
        pass

    cause = BackendFailure("backend failed")
    cause.transient = True
    cause.return_code = 23
    cause.elapsed = 1.25
    cause.command_mode = "stream-json"
    cause.session_source_event = "event[2]:result"
    cause.output = "stderr tail"
    cause.diagnostics = {
        "loop_type": "consecutive_identical_tool_calls",
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "plugin_error": "hook failed",
    }
    wrapped = RunnerError("wrapper")
    wrapped.__cause__ = cause

    assert diagnostic_error(wrapped) is cause
    assert is_transient_error(wrapped) is True
    parts = backend_diagnostic_parts(wrapped, include_output=True)
    assert "exit_code=23" in parts
    assert "elapsed_seconds=1.2" in parts
    assert "command_mode=stream-json" in parts
    assert "session_source_event=event[2]:result" in parts
    assert "loop_type=consecutive_identical_tool_calls" in parts
    assert "token_scope=backend_reported_not_current_context" in parts
    assert "stderr_tail=stderr tail" in parts
    assert len(diagnostic_detail(wrapped, limit=80)) <= 80
    assert is_transient_error(RunnerError("plain")) is False


def test_run_request_from_mapping_accepts_known_fields_and_rejects_removed_fields():
    request = RunRequest.from_mapping({"goal": "mapped goal", "validator": "ai"})
    assert request.goal == "mapped goal"
    assert request.validator == "ai"

    with pytest.raises(ValueError, match="unknown request fields: removed"):
        RunRequest.from_mapping({"goal": "x", "removed": True})


def test_register_resources_is_scoped_deduplicated_and_ignores_none(tmp_path):
    config = RuntimeConfig(
        goal="goal",
        project_root=str(tmp_path),
        validator="ai",
    )
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"

    register_resources([first])

    with runtime_scope(config) as runtime:
        register_resources([first, None, first, second])
        assert runtime.resources == [first.resolve(), second.resolve()]


def _stage_context(tmp_path: Path, *, tasks=None):
    state = RunState(
        "run-1",
        "goal",
        str(tmp_path),
        tasks=list(tasks or []),
    )
    ai = SimpleNamespace(session_id="main-session")
    saves = []
    stages = []
    ctx = StageContext(
        config=SimpleNamespace(workflow=[]),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=ai,
        state_file=tmp_path / ".work" / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: saves.append(state.dump()),
        set_stage=lambda stage, detail="": stages.append((stage, detail)),
    )
    return ctx, saves, stages


def test_stage_context_public_task_and_session_helpers(tmp_path):
    task = Task("task-1", "Task", "Do it")
    ctx, saves, _stages = _stage_context(tmp_path, tasks=[task])
    role_client = SimpleNamespace(session_id="role-session")
    ctx.scratch.update({
        "review_client": role_client,
        "prompt_contracts": {"x": 1},
        "other": object(),
    })
    ctx.state.stage_sessions = {"review": "role-session"}

    assert ctx.require_task("execute") is task

    ctx.save_session()
    assert ctx.state.ai_session_id == "main-session"
    assert len(saves) == 1

    ctx.reset_sessions()
    assert ctx.ai_client.session_id == ""
    assert role_client.session_id == ""
    assert ctx.state.ai_session_id == ""
    assert ctx.state.stage_sessions == {}
    assert "prompt_contracts" not in ctx.scratch
    assert len(saves) == 2

    ctx.state.current = 1
    with pytest.raises(RunnerError, match="execute stage requires a pending task"):
        ctx.require_task("execute")


def test_dynamic_task_and_done_target_public_helpers(tmp_path):
    state = RunState(
        "run-1",
        "goal",
        str(tmp_path),
        tasks=[
            Task("a", "A", "A"),
            Task("b", "B", "B"),
        ],
    )

    activate_dynamic_task(
        state,
        {"name": "child", "_dynamic_task_id": "b"},
    )
    assert state.current == 1

    with pytest.raises(ConfigurationError, match="unknown task"):
        activate_dynamic_task(
            state,
            {"name": "child", "_dynamic_task_id": "missing"},
        )

    assert dynamic_done_target({"name": "plain"}) is None
    assert dynamic_done_target({
        "name": "child",
        "_dynamic_group": "g1",
        "_dynamic_group_continue": "parent_next",
    }) == "parent_next"
    assert dynamic_done_target({
        "name": "child",
        "_dynamic_group": "g1",
        "_dynamic_group_continue": "",
    }) == "next"


def test_workflow_route_resolvers_cover_default_override_error_and_handoff():
    assert resolve_stage_target({"name": "x"}, "pass") == "next"
    assert resolve_stage_target({"name": "x"}, "fail") == "stop"
    assert resolve_stage_target(
        {"name": "x", "routes": {"pass": "done", "fail": "repair"}},
        "pass",
    ) == "done"
    assert resolve_stage_target(
        {"name": "x", "routes": {"pass": "done", "fail": "repair"}},
        "fail",
    ) == "repair"
    assert resolve_stage_target({"name": "x", "type": "base"}, "error") == "stop"
    assert resolve_stage_target(
        {
            "name": "review",
            "type": "base",
            "profile": "review",
            "error_policy": {"retries": 2},
        },
        "error",
    ) == "next"

    handoff = {"name": "route", "targets": ["alpha", "beta"]}
    assert resolve_handoff_target(
        handoff,
        StageResult("route", "pass", data={"target": "beta"}, kind="handoff"),
    ) == "beta"
    with pytest.raises(ConfigurationError, match="no structured target"):
        resolve_handoff_target(handoff, StageResult("route", "pass"))
    with pytest.raises(ConfigurationError, match="disallowed target"):
        resolve_handoff_target(
            handoff,
            StageResult(
                "route",
                "pass",
                data={"target": "outside"},
                kind="handoff",
            ),
        )


def test_build_flow_engine_and_finish_run_public_contract(tmp_path):
    ctx, _saves, stages = _stage_context(
        tmp_path,
        tasks=[Task("done", "Done", "Done", status="completed")],
    )
    ctx.config.workflow = [{"name": "only", "type": "command", "command": "echo ok"}]
    ctx.state.ai_session_id = "main-session"
    ctx.state.transition_previous = {"stage": "only"}
    ctx.state.stage_sessions = {"only": "stage-session"}
    ctx.state.review_failures = {"review::__run__": 1}
    ctx.state.dynamic_groups = {"producer": "g1"}
    ctx.state.dynamic_task_groups = {"producer": ["done"]}

    engine = build_flow_engine(ctx)
    assert isinstance(engine, FlowEngine)
    assert engine.workflow == ctx.config.workflow

    finish_run(ctx)
    assert ctx.state.completed is True
    assert ctx.state.ai_session_id == ""
    assert ctx.ai_client.session_id == ""
    assert ctx.state.transition_previous == {}
    assert ctx.state.stage_sessions == {}
    assert ctx.state.review_failures == {}
    assert ctx.state.dynamic_groups == {}
    assert ctx.state.dynamic_task_groups == {}
    assert stages[-1] == ("completed", "")

    pending, _saves, _stages = _stage_context(
        tmp_path,
        tasks=[Task("pending", "Pending", "Pending")],
    )
    with pytest.raises(ConfigurationError, match="pending planned tasks"):
        finish_run(pending)


def test_normalize_workflow_public_contract_assigns_indices_and_rejects_duplicates(
    tmp_path,
):
    source = tmp_path / "workflow.yaml"
    workflow = normalize_workflow(
        {
            "stages": {
                "first": {"type": "command", "command": "echo first"},
                "second": {"type": "command", "command": "echo second"},
            },
            "flow": ["first", "second"],
        },
        source,
    )
    assert [item["name"] for item in workflow] == ["first", "second"]
    assert [item["_workflow_index"] for item in workflow] == [0, 1]

    with pytest.raises(RunnerError, match="must be unique"):
        normalize_workflow(
            {
                "stages": {"first": {"type": "command", "command": "echo first"}},
                "flow": ["first", "first"],
            },
            source,
        )
