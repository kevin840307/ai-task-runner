from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.config.runtime import RuntimeConfig
from runner.errors import ConfigurationError, RunnerError
from runner.runtime.run_state import RunState, StateStore, Task, set_stage
from runner.workflow.flow_engine import FlowEngine
from runner.workflow.loader import WORKFLOWS, load_workflow
from runner.workflow.stages import HandoffStageSpec, StageContext, StageResult


ROOT = Path(__file__).resolve().parents[1]


class FakeAI:
    session_id = ""


class Executor:
    def __init__(self, results: dict[str, list[str] | str] | None = None):
        self.results = results or {}
        self.calls: list[tuple[str, StageResult | None]] = []
        self.retry_limits: list[int | None] = []
        self.counts: dict[str, int] = {}

    def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
        self.calls.append((stage.name, previous))
        self.retry_limits.append(retry_limit)
        configured = self.results.get(stage.name, "pass")
        values = configured if isinstance(configured, list) else [configured]
        index = self.counts.get(stage.name, 0)
        self.counts[stage.name] = index + 1
        status = values[min(index, len(values) - 1)]
        return StageResult(stage.name, status, output=f"{stage.name}:{status}")


def context(tmp_path: Path, workflow: list[dict]) -> StageContext:
    state = RunState("run", "goal", str(tmp_path))
    return StageContext(
        config=RuntimeConfig(
            goal="goal",
            project_root=str(tmp_path),
            workflow=workflow,
            workflow_explicit=True,
            stage_retries=0,
        ),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=FakeAI(),
        state_file=tmp_path / ".work" / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda stage, detail="": set_stage(state, stage, detail),
    )


def write_workflow(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "workflow.yaml"
    path.write_text(text.lstrip(), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "relative",
    [
        "tool/workflow/01_default_ai.yaml",
        "tool/workflow/02_ai_with_review_gate.yaml",
        "tool/workflow/03_file_validation.yaml",
        "tool/workflow/04_mixed_with_review_gate.yaml",
        "tool/workflow/05_review_vote_3_choose_2.yaml",
        "tool/workflow/06_custom_task_producer.yaml",
        "tool/workflow/11_multi_validators_anywhere.yaml",
    ],
)
def test_current_tool_workflow_examples_load_with_production_schema(relative):
    workflow = load_workflow(ROOT / relative)
    assert workflow
    assert all(item["name"] for item in workflow)


def test_public_workflow_yaml_uses_session_policy_not_legacy_fresh_flags():
    paths = [
        *WORKFLOWS.values(),
        ROOT / "tool" / "workflow" / "01_default_ai.yaml",
        ROOT / "tool" / "workflow" / "02_ai_with_review_gate.yaml",
        ROOT / "tool" / "workflow" / "03_file_validation.yaml",
        ROOT / "tool" / "workflow" / "04_mixed_with_review_gate.yaml",
        ROOT / "tool" / "workflow" / "05_review_vote_3_choose_2.yaml",
        ROOT / "tool" / "workflow" / "06_custom_task_producer.yaml",
        ROOT / "tool" / "workflow" / "11_multi_validators_anywhere.yaml",
        ROOT / "examples" / "11_regression_workflow_demo" / "workflow.yaml",
        ROOT / "examples" / "12_custom_stage_plugin" / "workflow.yaml",
        ROOT / "examples" / "custom_workflow_latest.yaml",
    ]
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        assert "fresh_session_each_run:" not in text, path
        assert "fresh_session_on_start:" not in text, path


@pytest.mark.parametrize(
    "legacy_option",
    ["fresh_session_each_run", "fresh_session_on_start"],
)
def test_removed_fresh_session_yaml_options_are_rejected(tmp_path, legacy_option):
    path = write_workflow(
        tmp_path,
        f"""
stages:
  worker:
    type: base
    {legacy_option}: true
flow:
  - worker
""",
    )

    with pytest.raises(RunnerError, match="unknown options"):
        load_workflow(path)


def test_builtin_workflow_keeps_plan_children_dynamic():
    workflow = load_workflow(WORKFLOWS["ai"])

    assert [item["name"] for item in workflow] == ["planning", "validate_ai"]
    assert workflow[0]["type"] == "plan"
    assert workflow[1]["type"] == "ai_validator"
    assert workflow[1]["routes"] == {"fail": "planning"}
    assert all("scope" not in item for item in workflow)


@pytest.mark.parametrize(
    "legacy",
    [
        "recover: [execute]",
        "restart_at: execute",
        "repeat: 2",
        "max_attempts: 3",
        "on_exhausted: continue",
        "fresh_after_same_failures: 2",
    ],
)
def test_removed_routing_fields_are_rejected(tmp_path, legacy):
    path = write_workflow(
        tmp_path,
        f"""
stages:
  execute:
    type: base
  review:
    type: base
    profile: review
    {legacy}
flow:
  - execute
  - review
""",
    )

    with pytest.raises(RunnerError, match="unknown options"):
        load_workflow(path)


def test_routes_support_only_pass_fail(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  a:
    routes:
      replan: a
flow:
  - a
""",
    )
    with pytest.raises(RunnerError, match="pass/fail"):
        load_workflow(path)


def test_route_target_must_exist(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  a:
    routes:
      fail: missing
flow:
  - a
""",
    )
    with pytest.raises(RunnerError, match="unknown stage"):
        load_workflow(path)


@pytest.mark.parametrize(
    "fields",
    ["backend: qwen", "model: qwen-only-model"],
)
def test_ai_stage_backend_model_must_be_configured_together(tmp_path, fields):
    path = write_workflow(
        tmp_path,
        f"""
stages:
  worker:
    type: base
    {fields}
flow:
  - worker
""",
    )
    with pytest.raises(ConfigurationError, match="backend and model must be configured together"):
        load_workflow(path)


def test_invalid_ai_stage_backend_fails_during_workflow_load(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  worker:
    type: base
    backend: does-not-exist
    model: unavailable-model
flow:
  - worker
""",
    )

    with pytest.raises(ConfigurationError, match="backend is unsupported"):
        load_workflow(path)


def test_ai_stage_backend_model_override_rejects_main_session_during_load(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  worker:
    type: base
    backend: opencode
    model: provider/model-x
    session_policy: main
flow:
  - worker
""",
    )

    with pytest.raises(ConfigurationError, match="session_policy=main"):
        load_workflow(path)


def test_ai_stage_model_length_is_validated_during_workflow_load(tmp_path):
    from runner.config.defaults import MAX_MODEL_NAME_CHARS

    model = "m" * (MAX_MODEL_NAME_CHARS + 1)
    path = write_workflow(
        tmp_path,
        f"""
stages:
  worker:
    type: base
    backend: qwen
    model: {model}
flow:
  - worker
""",
    )

    with pytest.raises(ConfigurationError, match="model is invalid"):
        load_workflow(path)


def test_error_policy_is_common_to_every_stage_type(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  work:
    type: base
    error_policy:
      retries: -1
  check:
    type: base
    profile: review
    error_policy:
      retries: 2
flow:
  - work
  - check
""",
    )

    workflow = load_workflow(path)
    assert workflow[0]["error_policy"] == {"retries": -1}
    assert workflow[1]["error_policy"] == {"retries": 2}


def test_error_route_is_rejected(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  work:
    type: base
    routes:
      error: stop
flow:
  - work
""",
    )

    with pytest.raises(RunnerError, match="pass/fail"):
        load_workflow(path)


def test_error_policy_has_only_retry_count(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  work:
    type: base
    error_policy:
      retries: 2
      exhausted: next
flow:
  - work
""",
    )

    with pytest.raises(RunnerError, match="requires only retries"):
        load_workflow(path)


def test_flow_node_names_must_be_unique(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  work:
    type: base
flow:
  - work
  - work
""",
    )
    with pytest.raises(RunnerError, match="must be unique"):
        load_workflow(path)


def test_flow_rejects_invocation_objects(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  work:
    type: base
flow:
  - stage: work
    name: first
""",
    )
    with pytest.raises(RunnerError, match="only Stage names"):
        load_workflow(path)


@pytest.mark.parametrize("stage_type", ["base", "plan", "ai_validator", "command", "handoff"])
def test_removed_scope_contract_is_rejected_for_every_stage(tmp_path, stage_type):
    extra = ""
    if stage_type == "command":
        extra = 'command: "echo ok"'
    elif stage_type == "handoff":
        extra = "targets: [worker]"
    elif stage_type == "ai_validator":
        extra = "validator: ai"
    path = write_workflow(
        tmp_path,
        f"""
stages:
  legacy:
    type: {stage_type}
    scope: task
    {extra}
  worker:
    type: base
flow:
  - legacy
  - worker
""",
    )
    with pytest.raises(RunnerError, match="unknown options"):
        load_workflow(path)


def test_fail_edge_closes_loop_without_recovery_framework(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  execute:
    type: base
  review:
    type: base
    profile: review
    routes:
      fail: execute
flow:
  - execute
  - review
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)
    executor = Executor({"review": ["fail", "pass"]})

    code = FlowEngine(ctx).run(executor)

    assert code == 0
    assert [name for name, _ in executor.calls] == [
        "execute",
        "review",
        "execute",
        "review",
    ]
    assert ctx.state.completed is True


def test_review_max_failures_bypasses_on_entry_after_configured_failures(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  execute:
    type: base
  review:
    type: base
    profile: review
    max_failures: 3
    routes:
      fail: execute
flow:
  - execute
  - review
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)
    executor = Executor({"review": ["fail", "fail", "fail"]})

    assert FlowEngine(ctx).run(executor) == 0
    assert [name for name, _ in executor.calls] == [
        "execute", "review",
        "execute", "review",
        "execute", "review",
        "execute",
    ]
    assert executor.counts["review"] == 3
    assert ctx.state.review_failures == {}
    assert ctx.state.completed is True
    assert ctx.state.transition_previous == {}


def test_review_max_failures_pass_clears_consecutive_counter(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  review:
    type: base
    profile: review
    max_failures: 3
flow:
  - review
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)
    engine = FlowEngine(ctx)
    definition = workflow[0]

    assert engine._review_bypass_result(definition) is None
    first = StageResult("review", "fail", data={
        "completed": False, "reason": "missing one", "missing_items": ["one"],
    }, kind="review")
    engine._record_review_result(definition, first)
    assert list(ctx.state.review_failures.values()) == [1]

    passed = StageResult("review", "pass", data={
        "completed": True, "reason": "done", "missing_items": [],
    }, kind="review")
    engine._record_review_result(definition, passed)
    assert ctx.state.review_failures == {}

    again = StageResult("review", "fail", data={
        "completed": False, "reason": "missing again", "missing_items": ["again"],
    }, kind="review")
    engine._record_review_result(definition, again)
    assert list(ctx.state.review_failures.values()) == [1]


def test_review_max_failures_fourth_entry_is_synthetic_pass(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  review:
    type: base
    profile: review
    max_failures: 3
flow:
  - review
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)
    engine = FlowEngine(ctx)
    definition = workflow[0]
    key = "review::__run__"
    ctx.state.review_failures[key] = 3

    result = engine._review_bypass_result(definition)

    assert result is not None
    assert result.status == "pass"
    assert result.data["bypassed"] is True
    assert result.data["failure_count"] == 3
    assert ctx.state.review_failures == {}


def test_finish_task_clears_task_review_failure_counters(tmp_path):
    workflow = [{"name": "review", "type": "base", "profile": "review", "max_failures": 3}]
    ctx = context(tmp_path, workflow)
    ctx.state.tasks = [Task(id="task-1", title="one", description="one")]
    ctx.state.review_failures = {
        "review::task-1": 2,
        "other_review::task-1": 1,
        "review::task-2": 3,
    }

    from runner.workflow.results import finish_task
    finish_task(ctx)

    assert ctx.state.review_failures == {"review::task-2": 3}


def test_review_max_failures_counter_survives_state_roundtrip(tmp_path):
    state = RunState("run", "goal", str(tmp_path))
    state.review_failures["review::task-1"] = 2

    restored = RunState.load(state.dump())

    assert restored.review_failures == {"review::task-1": 2}


def test_max_failures_is_review_only_and_positive(tmp_path):
    invalid_type = write_workflow(
        tmp_path,
        """
stages:
  execute:
    type: base
    profile: execute
    max_failures: 3
flow:
  - execute
""",
    )
    with pytest.raises(RunnerError, match="max_failures is only valid for Review semantics"):
        load_workflow(invalid_type)

    invalid_value = write_workflow(
        tmp_path,
        """
stages:
  review:
    type: base
    profile: review
    max_failures: 0
flow:
  - review
""",
    )
    with pytest.raises(RunnerError, match="max_failures must be a positive integer"):
        load_workflow(invalid_value)


def test_review_finite_error_policy_skips_after_exhausted_error(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  review:
    type: base
    profile: review
    error_policy:
      retries: 2
  validate:
    type: command
    command: "echo validate"
flow:
  - review
  - validate
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)

    class ErrorExecutor(Executor):
        def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
            self.calls.append((stage.name, previous))
            self.retry_limits.append(retry_limit)
            if stage.name == "review":
                return StageResult(stage.name, "error", output="review backend unavailable")
            return StageResult(stage.name, "pass", output="validated")

    executor = ErrorExecutor()
    assert FlowEngine(ctx).run(executor) == 0
    assert [name for name, _ in executor.calls] == ["review", "validate"]
    assert executor.retry_limits == [2, None]
    assert ctx.state.completed is True


def test_dynamic_plan_child_review_error_skip_finishes_each_task_and_continues(tmp_path):
    workflow = [
        {"name": "planning", "type": "plan"},
        {"name": "validate", "type": "command", "command": "echo validate"},
    ]
    ctx = context(tmp_path, workflow)

    tasks = [
        Task(id="t1", title="one", description="one"),
        Task(id="t2", title="two", description="two"),
    ]
    child_stages = []
    for index, task in enumerate(tasks, 1):
        execute = f"task_{index:03d}_execute"
        review = f"task_{index:03d}_review"
        child_stages.extend([
            {"name": execute, "type": "base", "profile": "execute", "task_id": task.id},
            {
                "name": review,
                "type": "base",
                "profile": "review",
                "task_id": task.id,
                "task_complete": True,
                "error_policy": {"retries": 2},
                "routes": {"fail": execute},
            },
        ])

    class ErrorReviewExecutor(Executor):
        def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
            self.calls.append((stage.name, previous))
            self.retry_limits.append(retry_limit)
            if stage.name == "planning":
                return StageResult(
                    "planning",
                    "pass",
                    output="planned",
                    data={"tasks": tasks, "stages": child_stages},
                    kind="tasks",
                )
            if stage.name.endswith("_review"):
                return StageResult(stage.name, "error", output="review unavailable")
            return StageResult(stage.name, "pass", output=stage.name)

    executor = ErrorReviewExecutor()
    assert FlowEngine(ctx).run(executor) == 0
    names = [name for name, _ in executor.calls]
    assert names[0] == "planning"
    assert names[-1] == "validate"
    assert [name for name in names if name.endswith("_execute")] == [
        "planning__g1__task_001_execute",
        "planning__g1__task_002_execute",
    ]
    assert [name for name in names if name.endswith("_review")] == [
        "planning__g1__task_001_review",
        "planning__g1__task_002_review",
    ]
    assert executor.retry_limits == [None, None, 2, None, 2, None]
    assert [task.status for task in ctx.state.tasks] == ["completed", "completed"]
    assert ctx.state.completed is True



def test_non_review_finite_error_policy_still_fails_closed(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  execute:
    type: base
    error_policy:
      retries: 2
  after:
    type: command
    command: "echo after"
flow:
  - execute
  - after
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)

    class ErrorExecutor(Executor):
        def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
            self.calls.append((stage.name, previous))
            return StageResult(stage.name, "error", output="technical failure")

    executor = ErrorExecutor()
    assert FlowEngine(ctx).run(executor) == 1
    assert [name for name, _ in executor.calls] == ["execute"]
    assert ctx.state.workflow_position == 0
    assert ctx.state.completed is False


def test_stage_error_policy_overrides_global_retry_limit(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  first:
    type: base
  second:
    type: base
    profile: review
    error_policy:
      retries: -1
flow:
  - first
  - second
""",
    )
    workflow = load_workflow(path)
    executor = Executor()

    assert FlowEngine(context(tmp_path, workflow)).run(executor) == 0
    assert executor.retry_limits == [None, -1]


def test_unrouted_fail_stops_safely(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  execute:
    type: base
flow:
  - execute
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)

    code = FlowEngine(ctx).run(Executor({"execute": "fail"}))

    assert code == 1
    assert ctx.state.completed is False
    assert ctx.state.workflow_position == 0


def test_explicit_done_completes_run(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  gate:
    type: base
    routes:
      pass: done
flow:
  - gate
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)

    assert FlowEngine(ctx).run(Executor()) == 0
    assert ctx.state.completed is True


def test_latest_transition_survives_resume_boundary(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  first:
    type: base
  second:
    type: base
flow:
  - first
  - second
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)
    ctx.state.workflow_position = 1
    ctx.state.transition_previous = {
        "stage": "first",
        "status": "pass",
        "output": "durable feedback",
        "changed_files": [],
        "data": {"evidence": "saved"},
        "kind": "generic",
    }
    executor = Executor()

    assert FlowEngine(ctx).run(executor) == 0
    assert executor.calls[0][0] == "second"
    previous = executor.calls[0][1]
    assert previous is not None
    assert previous.stage == "first"
    assert previous.output == "durable feedback"


def test_handoff_stage_defaults_to_durable_role_session():
    spec = HandoffStageSpec(name="router", targets=["worker"])
    assert spec.session_policy == "role"


def test_builtin_dynamic_handoff_workflow_uses_one_router_with_lean_roles():
    workflow = load_workflow(WORKFLOWS["dynamic_handoff"])
    coordinator = workflow[0]
    final_validate = workflow[-1]

    assert coordinator["type"] == "handoff"
    assert coordinator["targets"] == [
        "requirements_analyst",
        "solution_architect",
        "implementer",
        "debugger",
        "verifier",
        "final_validate",
    ]
    assert Path(coordinator["prompt"]).name == "dynamic_handoff.md"
    roles = {item["name"]: item for item in workflow[1:]}
    assert "risk_reviewer" not in roles
    assert coordinator["session_policy"] == "role"
    assert roles["requirements_analyst"]["session_policy"] == "role"
    assert roles["solution_architect"]["session_policy"] == "role"
    assert roles["implementer"]["session_policy"] == "role"
    assert roles["debugger"]["session_policy"] == "role"
    assert roles["verifier"]["session_policy"] == "role"
    verifier = str(roles["verifier"].get("instructions") or "")
    assert all(term in verifier for term in ("reliability", "security", "maintainability"))
    assert final_validate["type"] == "ai_validator"
    assert final_validate["session_policy"] == "fresh"
    assert all(
        stage["session_policy"] == "role"
        for stage in workflow[:-1]
    )
    assert final_validate["routes"] == {"pass": "done", "fail": "coordinator"}


def test_dynamic_worker_prompt_renders_stage_instructions():
    prompt_root = Path(WORKFLOWS["dynamic_handoff"]).parent.parent / "prompts" / "common"
    worker = (prompt_root / "dynamic_worker.md").read_text(encoding="utf-8")
    coordinator = (prompt_root / "dynamic_handoff.md").read_text(encoding="utf-8")

    assert "{{ instructions }}" in worker
    assert "Assigned responsibility:" in worker
    assert "do not repeat analysis or reads already established" in worker
    assert "remaining blocker or risk" in worker

    assert "{{ goal }}" in coordinator
    assert "{{ previous }}" in coordinator
    assert "avoid unnecessary analysis roles" in coordinator
    assert "final validation" in coordinator


@pytest.mark.parametrize("policy", ["main", "role", "fresh"])
def test_session_policy_accepts_dynamic_role_modes(tmp_path, policy):
    path = write_workflow(
        tmp_path,
        f"""
stages:
  router:
    type: handoff
    targets: [worker]
  worker:
    type: base
    session_policy: {policy}
flow:
  - router
  - worker
""",
    )

    workflow = load_workflow(path)
    assert workflow[1]["session_policy"] == policy


def test_removed_session_key_is_rejected_as_unknown_option(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  worker:
    type: base
    session_key: conflicting_key
flow:
  - worker
""",
    )

    with pytest.raises(RunnerError, match="unknown options"):
        load_workflow(path)


def test_session_policy_rejects_unknown_mode(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  worker:
    type: base
    session_policy: shared_magic
flow:
  - worker
""",
    )

    with pytest.raises(RunnerError, match="session_policy"):
        load_workflow(path)


def test_removed_discussion_stage_types_are_rejected(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  old:
    type: discussion_controller
    targets: [worker]
  worker:
    type: base
flow:
  - old
  - worker
""",
    )

    with pytest.raises(RunnerError, match="unknown type"):
        load_workflow(path)


def test_removed_discussion_options_are_rejected(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [worker]
    max_rounds: 3
  worker:
    type: base
flow:
  - router
  - worker
""",
    )

    with pytest.raises(RunnerError, match="unknown options"):
        load_workflow(path)


@pytest.mark.parametrize(
    ("targets", "message"),
    [
        ("[]", "non-empty array"),
        ("[worker, worker]", "must be unique"),
    ],
)
def test_handoff_rejects_invalid_target_lists(tmp_path, targets, message):
    path = write_workflow(
        tmp_path,
        f"""
stages:
  router:
    type: handoff
    targets: {targets}
  worker:
    type: base
flow:
  - router
  - worker
""",
    )

    with pytest.raises(RunnerError, match=message):
        load_workflow(path)


def test_handoff_cannot_target_itself(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [router]
flow:
  - router
""",
    )

    with pytest.raises(RunnerError, match="cannot hand off to itself"):
        load_workflow(path)


def test_handoff_runtime_rejects_missing_structured_target(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [worker]
  worker:
    type: base
flow:
  - router
  - worker
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)

    class MissingTargetExecutor(Executor):
        def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
            if stage.name == "router":
                return StageResult(
                    "router",
                    "pass",
                    output="missing target",
                    data=None,
                    kind="handoff",
                )
            return StageResult(stage.name, "pass")

    with pytest.raises(ConfigurationError, match="no structured target"):
        FlowEngine(ctx).run(MissingTargetExecutor())


def test_handoff_runtime_rejects_model_target_outside_allow_list(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [worker]
  worker:
    type: base
flow:
  - router
  - worker
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)

    class InvalidTargetExecutor(Executor):
        def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
            if stage.name == "router":
                return StageResult(
                    "router",
                    "pass",
                    data={"target": "not_allowed", "reason": "bad model output"},
                    kind="handoff",
                )
            return StageResult(stage.name, "pass")

    with pytest.raises(ConfigurationError, match="selected disallowed target"):
        FlowEngine(ctx).run(InvalidTargetExecutor())


def test_dynamic_handoff_respects_global_max_cycles(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [worker]
  worker:
    type: base
    routes:
      pass: router
flow:
  - router
  - worker
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)
    ctx.config.max_cycles = 2

    class LoopingHandoffExecutor(Executor):
        def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
            self.calls.append((stage.name, previous))
            if stage.name == "router":
                return StageResult(
                    "router",
                    "pass",
                    data={"target": "worker", "reason": "continue"},
                    kind="handoff",
                )
            return StageResult("worker", "pass", output="done")

    executor = LoopingHandoffExecutor()
    assert FlowEngine(ctx).run(executor) == 2
    assert [name for name, _ in executor.calls] == [
        "router", "worker", "router", "worker"
    ]
    assert ctx.state.cycle == 3
    assert ctx.state.stage == "max_cycles_exhausted"


def test_handoff_target_must_exist(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [missing]
  worker:
    type: base
flow:
  - router
  - worker
""",
    )

    with pytest.raises(RunnerError, match="handoff target"):
        load_workflow(path)


def test_dynamic_handoff_routes_exactly_one_selected_stage_then_final_validation(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [worker, final_validate]
  worker:
    type: base
    session_policy: role
    routes:
      pass: router
  final_validate:
    type: ai_validator
    validator: ai
    session_policy: fresh
    routes:
      pass: done
      fail: router
flow:
  - router
  - worker
  - final_validate
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)

    class HandoffExecutor(Executor):
        def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
            self.calls.append((stage.name, previous))
            self.retry_limits.append(retry_limit)
            count = self.counts.get(stage.name, 0)
            self.counts[stage.name] = count + 1
            if stage.name == "router":
                target = "worker" if count == 0 else "final_validate"
                return StageResult(
                    stage.name,
                    "pass",
                    output=f"handoff:{target}",
                    data={"target": target, "reason": "test"},
                    kind="handoff",
                )
            return StageResult(stage.name, "pass", output=f"{stage.name}:pass")

    executor = HandoffExecutor()
    assert FlowEngine(ctx).run(executor) == 0
    assert [name for name, _ in executor.calls] == [
        "router",
        "worker",
        "router",
        "final_validate",
    ]
    assert ctx.state.completed is True


@pytest.mark.parametrize(
    ("error_stage", "expected_calls", "expected_position"),
    [
        ("router", ["router"], 0),
        ("worker", ["router", "worker"], 1),
        ("final_validate", ["router", "final_validate"], 2),
    ],
)
def test_dynamic_technical_error_stops_at_current_stage(
    tmp_path, error_stage, expected_calls, expected_position
):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [worker, final_validate]
  worker:
    type: base
    routes:
      pass: router
  final_validate:
    type: ai_validator
    validator: ai
    routes:
      pass: done
      fail: router
flow:
  - router
  - worker
  - final_validate
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)

    class DynamicErrorExecutor(Executor):
        def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
            self.calls.append((stage.name, previous))
            if stage.name == error_stage:
                return StageResult(stage.name, "error", output="technical failure")
            if stage.name == "router":
                target = error_stage
                return StageResult(
                    "router",
                    "pass",
                    output=f"handoff:{target}",
                    data={"target": target, "reason": "exercise error boundary"},
                    kind="handoff",
                )
            return StageResult(stage.name, "pass", output="pass")

    executor = DynamicErrorExecutor()
    assert FlowEngine(ctx).run(executor) == 1
    assert [name for name, _ in executor.calls] == expected_calls
    assert ctx.state.workflow_position == expected_position
    assert ctx.state.completed is False


def test_dynamic_final_validation_fail_returns_to_handoff(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [worker, final_validate]
  worker:
    type: base
    routes:
      pass: router
  final_validate:
    type: ai_validator
    validator: ai
    routes:
      pass: done
      fail: router
flow:
  - router
  - worker
  - final_validate
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)

    class ValidatorFailExecutor(Executor):
        choices = ["final_validate", "worker", "final_validate"]

        def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
            self.calls.append((stage.name, previous))
            self.retry_limits.append(retry_limit)
            count = self.counts.get(stage.name, 0)
            self.counts[stage.name] = count + 1
            if stage.name == "router":
                target = self.choices[count]
                return StageResult(
                    "router",
                    "pass",
                    output=f"handoff:{target}",
                    data={"target": target, "reason": "test"},
                    kind="handoff",
                )
            if stage.name == "final_validate" and count == 0:
                return StageResult("final_validate", "fail", output="more work needed")
            return StageResult(stage.name, "pass", output=f"{stage.name}:pass")

    executor = ValidatorFailExecutor()
    assert FlowEngine(ctx).run(executor) == 0
    assert [name for name, _ in executor.calls] == [
        "router",
        "final_validate",
        "router",
        "worker",
        "router",
        "final_validate",
    ]
    assert ctx.state.completed is True


def test_dynamic_handoff_state_store_resume_continues_selected_target(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [worker, final_validate]
  worker:
    type: base
    session_policy: role
    routes:
      pass: router
  final_validate:
    type: ai_validator
    validator: ai
    routes:
      pass: done
      fail: router
flow:
  - router
  - worker
  - final_validate
""",
    )
    workflow = load_workflow(path)
    work = tmp_path / ".work"
    store = StateStore(tmp_path, work)
    state = RunState("run", "goal", str(tmp_path))
    state.workflow_position = 1
    state.stage_sessions = {"worker": "durable-role-session"}
    state.transition_previous = {
        "stage": "router",
        "status": "pass",
        "output": "handoff:worker",
        "changed_files": [],
        "data": {"target": "worker", "reason": "resume test"},
        "kind": "handoff",
    }
    store.save(state)

    resumed = store.load_or_create("", resume=True, force_new=False)
    assert resumed.stage_sessions == {"worker": "durable-role-session"}
    ctx = context(tmp_path, workflow)
    ctx.state = resumed

    class ResumeHandoffExecutor(Executor):
        def run(self, stage, ctx, previous=None, *, label="", retry_limit=None):
            self.calls.append((stage.name, previous))
            self.retry_limits.append(retry_limit)
            if stage.name == "router":
                return StageResult(
                    "router",
                    "pass",
                    output="handoff:final_validate",
                    data={"target": "final_validate", "reason": "worker completed"},
                    kind="handoff",
                )
            return StageResult(stage.name, "pass", output=f"{stage.name}:pass")

    executor = ResumeHandoffExecutor()
    assert FlowEngine(ctx).run(executor) == 0
    assert [name for name, _ in executor.calls] == [
        "worker",
        "router",
        "final_validate",
    ]
    previous = executor.calls[0][1]
    assert previous is not None
    assert previous.kind == "handoff"
    assert previous.data == {"target": "worker", "reason": "resume test"}
    assert ctx.state.completed is True

def test_ai_profile_defaults_are_applied_by_workflow_normalization(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  generic:
    type: base
  review:
    type: base
    profile: review
flow:
  - generic
  - review
""",
    )

    workflow = load_workflow(path)
    generic, review = workflow

    assert generic["profile"] == "generic"
    assert Path(generic["prompt"]).name == "generic.md"
    assert review["profile"] == "review"
    assert Path(review["prompt"]).name == "review.md"
    assert review["error_policy"] == {"retries": 2}
    assert review["max_failures"] == 3
    assert review["readonly_safety"] == "observe"


def test_dynamic_review_child_uses_shared_profile_defaults():
    from runner.workflow.dynamic_expansion import expand_stage_result

    state = RunState("run", "goal", "/tmp/project")
    workflow = [
        {"name": "producer", "type": "base", "produces": "stages"},
        {"name": "after", "type": "base"},
    ]
    result = StageResult(
        "producer",
        "pass",
        data={
            "stages": [
                {"name": "review", "type": "base", "profile": "review"}
            ]
        },
        kind="stages",
    )

    expanded = expand_stage_result(
        state=state,
        workflow=workflow,
        source_index=0,
        source=workflow[0],
        result=result,
        continuation="next",
    )

    child = expanded[1]
    assert child["profile"] == "review"
    assert child["error_policy"] == {"retries": 2}
    assert child["max_failures"] == 3
    assert child["readonly_safety"] == "observe"



def test_ai_stage_backend_and_model_overrides_load_from_yaml(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  worker:
    type: base
    profile: execute
    backend: opencode
    model: provider/model-a
    session_policy: auto
flow:
  - worker
""",
    )

    workflow = load_workflow(path)

    assert workflow[0]["backend"] == "opencode"
    assert workflow[0]["model"] == "provider/model-a"
    assert workflow[0]["session_policy"] == "auto"


def test_ai_stage_backend_override_rejects_main_session(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  worker:
    type: base
    backend: opencode
    model: provider/model-a
    session_policy: main
flow:
  - worker
""",
    )

    with pytest.raises(ConfigurationError, match="session_policy=main"):
        from runner.workflow.registry import create_stage
        create_stage(load_workflow(path)[0])
