from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.config.runtime import RuntimeConfig
from runner.errors import RunnerError
from runner.runtime.run_state import RunState, StateStore, set_stage
from runner.workflow.flow_engine import FlowEngine
from runner.workflow.loader import WORKFLOWS, load_workflow
from runner.workflow.stages import StageContext, StageResult


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


def test_builtin_workflow_has_explicit_plan_task_review_validate_nodes():
    workflow = load_workflow(WORKFLOWS["ai"])

    assert [item["name"] for item in workflow] == [
        "planning",
        "execute",
        "review",
        "validate_ai",
    ]
    assert workflow[1]["scope"] == "task"
    assert workflow[2]["scope"] == "task"
    assert workflow[2]["error_policy"] == {"retries": 2}
    assert workflow[2]["routes"] == {"fail": "execute"}
    assert workflow[3]["routes"] == {"fail": "planning"}


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
    type: review
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
    type: review
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


def test_task_scope_must_be_one_contiguous_block(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  a: {type: base, scope: task}
  b: {type: base}
  c: {type: base, scope: task}
flow:
  - a
  - b
  - c
""",
    )
    with pytest.raises(RunnerError, match="contiguous"):
        load_workflow(path)


def test_validator_cannot_run_inside_task_scope(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  validate:
    type: ai_validator
    validator: ai
    scope: task
flow:
  - validate
""",
    )
    with pytest.raises(RunnerError, match="validator stages cannot use scope"):
        load_workflow(path)


def test_fail_edge_closes_loop_without_recovery_framework(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  execute:
    type: base
  review:
    type: review
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


def test_stage_error_policy_overrides_global_retry_limit(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  first:
    type: base
  second:
    type: review
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


def test_builtin_dynamic_handoff_workflow_uses_one_router_with_many_targets():
    workflow = load_workflow(WORKFLOWS["dynamic_handoff"])
    coordinator = workflow[0]
    final_review = workflow[-1]

    assert coordinator["type"] == "handoff"
    assert coordinator["targets"] == ["implementer", "verifier", "final_review"]
    assert final_review["type"] == "review"
    assert final_review["routes"] == {"pass": "done", "fail": "coordinator"}


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


def test_dynamic_handoff_routes_selected_target_and_final_review_ends(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [worker, final_review]
  worker:
    type: base
    routes:
      pass: router
  final_review:
    type: review
    routes:
      fail: router
flow:
  - router
  - worker
  - final_review
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
                target = "worker" if count == 0 else "final_review"
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
        "final_review",
    ]
    assert ctx.state.completed is True


def test_builtin_discussion_workflow_is_bounded_by_judge_rounds():
    workflow = load_workflow(WORKFLOWS["discussion"])
    assert [item["type"] for item in workflow] == [
        "discussion",
        "discussion",
        "discussion",
        "review",
    ]
    assert workflow[-1]["max_rounds"] == 3
    assert workflow[-1]["routes"] == {"fail": "participant_architecture"}


def test_discussion_round_limit_stops_after_bounded_backward_routes(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  participant:
    type: discussion
    role: participant
  moderator:
    type: discussion
    role: moderator
  judge:
    type: review
    max_rounds: 2
    routes:
      fail: participant
flow:
  - participant
  - moderator
  - judge
""",
    )
    workflow = load_workflow(path)
    ctx = context(tmp_path, workflow)
    executor = Executor({"judge": "fail"})

    assert FlowEngine(ctx).run(executor) == 1
    assert [name for name, _ in executor.calls] == [
        "participant",
        "moderator",
        "judge",
        "participant",
        "moderator",
        "judge",
    ]
    assert ctx.state.cycle == 2
    assert ctx.state.stage == "max_rounds_exhausted"
    assert ctx.state.completed is False


def test_dynamic_handoff_state_store_resume_continues_selected_target(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  router:
    type: handoff
    targets: [worker, final_review]
  worker:
    type: base
    routes:
      pass: router
  final_review:
    type: review
    routes:
      pass: done
      fail: router
flow:
  - router
  - worker
  - final_review
""",
    )
    workflow = load_workflow(path)
    work = tmp_path / ".work"
    store = StateStore(tmp_path, work)
    state = RunState("run", "goal", str(tmp_path))
    state.workflow_position = 1
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
                    output="handoff:final_review",
                    data={"target": "final_review", "reason": "worker completed"},
                    kind="handoff",
                )
            return StageResult(stage.name, "pass", output=f"{stage.name}:pass")

    executor = ResumeHandoffExecutor()
    assert FlowEngine(ctx).run(executor) == 0
    assert [name for name, _ in executor.calls] == [
        "worker",
        "router",
        "final_review",
    ]
    previous = executor.calls[0][1]
    assert previous is not None
    assert previous.kind == "handoff"
    assert previous.data == {"target": "worker", "reason": "resume test"}
    assert ctx.state.completed is True


def test_discussion_state_store_resume_preserves_round_order_and_history(tmp_path):
    path = write_workflow(
        tmp_path,
        """
stages:
  participant:
    type: discussion
    role: participant
  moderator:
    type: discussion
    role: moderator
  judge:
    type: review
    max_rounds: 3
    routes:
      pass: done
      fail: participant
flow:
  - participant
  - moderator
  - judge
""",
    )
    workflow = load_workflow(path)
    work = tmp_path / ".work"
    store = StateStore(tmp_path, work)
    state = RunState("run", "goal", str(tmp_path))
    state.cycle = 2
    state.workflow_position = 1
    state.discussion_history = [
        {
            "stage": "participant",
            "role": "participant",
            "message": "Persisted round-two evidence",
        }
    ]
    state.transition_previous = {
        "stage": "participant",
        "status": "pass",
        "output": "Persisted round-two evidence",
        "changed_files": [],
        "data": "Persisted round-two evidence",
        "kind": "discussion",
    }
    store.save(state)

    resumed = store.load_or_create("", resume=True, force_new=False)
    ctx = context(tmp_path, workflow)
    ctx.state = resumed
    executor = Executor()

    assert FlowEngine(ctx).run(executor) == 0
    assert [name for name, _ in executor.calls] == ["moderator", "judge"]
    assert ctx.state.cycle == 2
    assert ctx.state.discussion_history == [
        {
            "stage": "participant",
            "role": "participant",
            "message": "Persisted round-two evidence",
        }
    ]
    previous = executor.calls[0][1]
    assert previous is not None
    assert previous.kind == "discussion"
    assert previous.output == "Persisted round-two evidence"
    assert ctx.state.completed is True
