from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from runner.config.runtime import RuntimeConfig
from runner.runtime.run_state import RunState
from runner.workflow.loader import load_workflow
from runner.workflow.pipeline import Pipeline
from runner.workflow.registry import STAGE_REGISTRY, create_stage, register_stage, stage_catalog
from runner.workflow.stages.contracts import StageContext, StageResult
from runner.workflow.stages.executor import StageExecutor


@dataclass(frozen=True)
class ExtensionSpec:
    name: str
    status: str = "Extension"
    message: str = "OK"
    retry: int | None = 0


class ExtensionStage:
    """Test-only Stage proving ordinary extensions need no Core branch."""

    spec_class = ExtensionSpec
    result_kind = "generic"
    mode = "readonly"
    actor = "extension"
    detail = ""
    run_state = ""
    track_changes = False
    tolerate_restored_changes = False
    skip_on_error = False
    fresh_session_on_start = False

    def __init__(self, spec: ExtensionSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.status = spec.status
        self.retry = spec.retry

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        return StageResult(self.name, "pass", output=self.spec.message)

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        return result


class Hooks:
    def before(self, action):
        return []

    def after(self, action, tokens):
        return []

    def change_detector(self, action, tokens, fallback):
        return fallback()


def _context(tmp_path: Path, workflow: list[dict]) -> StageContext:
    state = RunState("run", "goal", str(tmp_path))
    config = RuntimeConfig(
        project_root=str(tmp_path),
        goal="goal",
        workflow=workflow,
        workflow_explicit=True,
        same_session_retries=0,
        stage_retry_delay=0,
    )
    return StageContext(
        config=config,
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=SimpleNamespace(session_id=""),
        state_file=tmp_path / ".work" / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda stage, detail="": setattr(state, "stage", stage),
    )


def test_registered_stage_flows_catalog_schema_factory_and_pipeline_without_core_changes(tmp_path):
    name = "contract_extension"
    register_stage(name, ExtensionStage)
    try:
        workflow_file = tmp_path / "workflow.yaml"
        workflow_file.write_text(
            """
stages:
  extension:
    type: contract_extension
    message: EXTENSION_OK
flow:
  - extension
""".lstrip(),
            encoding="utf-8",
        )

        catalog = stage_catalog()
        assert name in catalog
        assert {item["name"] for item in catalog[name]["options"]} >= {"status", "message", "retry"}

        workflow = load_workflow(workflow_file)
        stage = create_stage(workflow[0])
        assert isinstance(stage, ExtensionStage)
        assert stage.spec.message == "EXTENSION_OK"

        ctx = _context(tmp_path, workflow)
        Pipeline(ctx, workflow).run(StageExecutor(Hooks()))

        assert ctx.state.completed is True
        assert ctx.state.workflow_position == 1
    finally:
        STAGE_REGISTRY.pop(name, None)


@dataclass(frozen=True)
class TaskProducerSpec:
    name: str
    status: str = "Task Producer"
    retry: int | None = 0
    produces: str = "tasks"


class TaskProducerStage:
    """Test-only Task producer proving Task[] is an effect, not a PlanStage privilege."""

    spec_class = TaskProducerSpec
    result_kind = "generic"
    mode = "readonly"
    actor = "extension"
    detail = ""
    run_state = ""
    track_changes = False
    tolerate_restored_changes = False
    skip_on_error = False
    fresh_session_on_start = False

    def __init__(self, spec: TaskProducerSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.status = spec.status
        self.retry = spec.retry

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        return StageResult(
            self.name,
            "pass",
            output="TASKS_READY",
            data={
                "tasks": [
                    {
                        "title": "Extension task",
                        "description": "Exercise a task-scoped Stage from a custom producer.",
                        "deliverable": "Completed extension task",
                        "acceptance_criteria": ["The task-scoped Stage completes."],
                    }
                ]
            },
        )

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        return result


def test_registered_task_producer_drives_task_scope_without_plan_or_core_changes(tmp_path):
    producer_name = "contract_task_producer"
    consumer_name = "contract_task_consumer"
    register_stage(producer_name, TaskProducerStage)
    register_stage(consumer_name, ExtensionStage)
    try:
        workflow_file = tmp_path / "workflow.yaml"
        workflow_file.write_text(
            f"""
stages:
  discover:
    type: {producer_name}
    produces: tasks
  execute:
    type: {consumer_name}
    message: TASK_CONSUMED
flow:
  - discover
  - stage: execute
    scope: task
""".lstrip(),
            encoding="utf-8",
        )

        workflow = load_workflow(workflow_file)
        ctx = _context(tmp_path, workflow)
        Pipeline(ctx, workflow).run(StageExecutor(Hooks()))

        assert ctx.state.completed is True
        assert len(ctx.state.tasks) == 1
        assert ctx.state.tasks[0].status == "completed"
        assert ctx.state.current == 1
    finally:
        STAGE_REGISTRY.pop(producer_name, None)
        STAGE_REGISTRY.pop(consumer_name, None)
