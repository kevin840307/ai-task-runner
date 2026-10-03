from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from runner.config.runtime import RuntimeConfig
from runner.runtime.run_state import RunState
from runner.workflow.loader import load_workflow
from runner.workflow.flow_engine import FlowEngine
from runner.workflow.registry import STAGE_REGISTRY, create_stage, register_stage, stage_catalog
from runner.workflow.stages import StageContext, StageResult
from runner.workflow.execution import StageExecutor


@dataclass(frozen=True)
class ExtensionSpec:
    name: str
    status: str = "Extension"
    message: str = "OK"


class ExtensionStage:
    """Test-only Stage proving ordinary extensions need no Core/UI branch."""

    spec_class = ExtensionSpec
    ui_title = "Contract Extension"
    ui_description = "Test plugin Stage"
    ui_category = "testing"
    result_kind = "generic"
    mode = "readonly"
    actor = "extension"
    detail = ""
    run_state = ""
    track_changes = False
    tolerate_restored_changes = False
    fresh_session_on_start = False

    def __init__(self, spec: ExtensionSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.status = spec.status

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
        stage_retries=0,
        retry_delay=0,
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
        assert catalog[name]["title"] == "Contract Extension"
        assert catalog[name]["description"] == "Test plugin Stage"
        assert catalog[name]["category"] == "testing"
        assert {item["name"] for item in catalog[name]["options"]} >= {"status", "message"}

        workflow = load_workflow(workflow_file)
        stage = create_stage(workflow[0])
        assert isinstance(stage, ExtensionStage)
        assert stage.spec.message == "EXTENSION_OK"

        ctx = _context(tmp_path, workflow)
        FlowEngine(ctx).run(StageExecutor(Hooks()))

        assert ctx.state.completed is True
        assert ctx.state.workflow_position == 1
    finally:
        STAGE_REGISTRY.pop(name, None)


@dataclass(frozen=True)
class TaskProducerSpec:
    name: str
    status: str = "Task Producer"
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
    fresh_session_on_start = False

    def __init__(self, spec: TaskProducerSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.status = spec.status

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        return StageResult(
            self.name,
            "pass",
            output="TASKS_READY",
            data={
                "tasks": [
                    {
                        "title": "Extension task",
                        "description": "Exercise producer-defined child Stages.",
                        "deliverable": "Completed extension task",
                        "acceptance_criteria": ["The producer-defined child Workflow completes."],
                    }
                ],
                "stages": [
                    {
                        "name": "child_execute",
                        "type": "contract_task_consumer",
                        "message": "TASK_CONSUMED",
                        "task_id": "c01-t001",
                    },
                    {
                        "name": "child_done",
                        "type": "contract_task_consumer",
                        "message": "TASK_COMPLETE",
                        "task_id": "c01-t001",
                        "task_complete": True,
                    },
                ],
            },
        )

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        return result


def test_registered_task_producer_expands_its_own_child_workflow_without_core_changes(tmp_path):
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
  after:
    type: {consumer_name}
    message: PARENT_CONTINUED
flow:
  - discover
  - after
""".lstrip(),
            encoding="utf-8",
        )

        workflow = load_workflow(workflow_file)
        ctx = _context(tmp_path, workflow)
        FlowEngine(ctx).run(StageExecutor(Hooks()))

        assert ctx.state.completed is True
        assert len(ctx.state.tasks) == 1
        assert ctx.state.tasks[0].status == "completed"
        assert ctx.state.current == 1
        names = [item["name"] for item in ctx.state.expanded_workflow]
        assert names[0] == "discover"
        assert names[1].endswith("__child_execute")
        assert names[2].endswith("__child_done")
        assert names[3] == "after"
    finally:
        STAGE_REGISTRY.pop(producer_name, None)
        STAGE_REGISTRY.pop(consumer_name, None)



def test_explicit_produces_overrides_ai_profile_result_kind():
    from runner.workflow.registry import stage_result_kind

    assert stage_result_kind({
        "name": "generator",
        "type": "base",
        "profile": "execute",
        "produces": "stages",
    }) == "stages"
    assert stage_result_kind({
        "name": "generator",
        "type": "base",
        "profile": "review",
        "produces": "tasks",
    }) == "tasks"

def test_ai_stage_catalog_exposes_profile_metadata_for_studio():
    catalog = stage_catalog()
    profiles = catalog["base"]["profiles"]

    assert set(profiles) == {"generic", "execute", "review"}
    assert profiles["generic"]["defaults"]["prompt"] == "common/generic.md"
    assert profiles["execute"]["defaults"]["prompt"] == "common/execution.md"
    assert profiles["review"]["defaults"]["prompt"] == "common/review.md"
    assert profiles["review"]["defaults"]["error_policy"] == {"retries": 2}
    assert profiles["review"]["defaults"]["max_failures"] == 3



def test_catalog_exposes_dynamic_output_metadata_for_special_stages():
    catalog = stage_catalog()
    assert catalog["plan"]["result_kind"] == "tasks"
    assert catalog["plan"]["dynamic_output"] is True
    assert catalog["base"]["dynamic_output"] is False
