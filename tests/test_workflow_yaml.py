from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.config.runtime import RuntimeConfig
from runner.errors import RunnerError
from runner.runtime.run_state import RunState, set_stage
from runner.workflow.flow_engine import FlowEngine
from runner.workflow.loader import SYSTEM_WORKFLOWS, load_workflow
from runner.workflow.stages.contracts import StageContext, StageResult


class FakeAI:
    session_id = ""


class Executor:
    def __init__(self, results: dict[str, list[str] | str] | None = None):
        self.results = results or {}
        self.calls: list[tuple[str, StageResult | None]] = []
        self.counts: dict[str, int] = {}

    def run(self, stage, ctx, previous=None, *, label=""):
        self.calls.append((stage.name, previous))
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


def test_system_workflow_has_explicit_plan_task_review_validate_nodes():
    workflow = load_workflow(SYSTEM_WORKFLOWS["ai"])

    assert [item["name"] for item in workflow] == [
        "planning",
        "execute",
        "review",
        "validate_ai",
    ]
    assert workflow[1]["scope"] == "task"
    assert workflow[2]["scope"] == "task"
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


def test_routes_support_only_pass_fail_error(tmp_path):
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
    with pytest.raises(RunnerError, match="pass/fail/error"):
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
