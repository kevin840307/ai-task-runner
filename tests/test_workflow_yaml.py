from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from runner.api import RunRequest
from runner.config import RuntimeConfig
from runner.errors import RunnerError
from runner.runtime.run_state import RunState, Task
from runner.workflow.loader import (
    BUILTIN_WORKFLOW_DIR,
    BUILTIN_WORKFLOWS,
    load_workflow,
    workflow_fingerprint,
    workflow_has_planning,
    workflow_validators,
)
from runner.workflow.pipeline import FlowNode
from runner.workflow.registry import STAGE_REGISTRY, create_stage, register_stage
from runner.workflow.rules import handle_validation_result
from runner.workflow.stages.contracts import StageContext, StageResult


class FakeAI:
    session_id = ""


@dataclass(frozen=True)
class ProbeSpec:
    name: str
    status: str
    value: str = "default"


class ProbeStage:
    spec_class = ProbeSpec

    def __init__(self, spec: ProbeSpec):
        self.spec = spec
        self.name = spec.name


def _context(tmp_path: Path, workflow, state: RunState | None = None) -> StageContext:
    return StageContext(
        config=RuntimeConfig(workflow=workflow),
        root=tmp_path,
        work=tmp_path / ".ai-task-runner",
        state=state or RunState("run", "goal", str(tmp_path)),
        ai_client=FakeAI(),
        state_file=tmp_path / "state.json",
        validator_path=None,
        validator_is_ai=True,
        save_state=lambda: None,
        set_stage=lambda *_: None,
    )


def _names(workflow):
    return [item["name"] for item in workflow]


def test_default_workflow_plan_receives_dynamic_stage_catalog():
    workflow = load_workflow()
    assert _names(workflow) == ["planning", "validate_file", "validate_ai"]
    catalog = workflow[0]["planner_stages"]
    assert list(catalog) == ["execute", "review"]
    assert catalog["review"]["recover"][0]["name"] == "repair"
    assert "expand" not in workflow[0]


def test_planner_catalog_auto_includes_new_dynamic_stage(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  planning:
    type: plan
    status: Plan
    result_handler: plan
  execute:
    status: Execute
    result_handler: task
  security_review:
    status: Security review
  review:
    status: Review
    result_handler: review
  repair:
    status: Repair
  validate:
    type: python
    validator: file
    status: Validate
    recover: [repair]
flow: [planning, validate]
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    assert list(workflow[0]["planner_stages"]) == [
        "execute", "security_review", "review"
    ]


def test_plan_stage_generates_selected_dynamic_stage_sequence(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  planning:
    type: plan
    status: Plan
    result_handler: plan
  execute:
    status: Execute
    result_handler: task
  security_review:
    status: Security review
  review:
    status: Review
    result_handler: review
  validate:
    type: python
    validator: file
    status: Validate
flow: [planning, validate]
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    context = _context(tmp_path, workflow)
    stage = create_stage(workflow[0])
    payload = json.dumps({
        "tasks": [{
            "title": "Secure feature",
            "description": "Implement and security-check the feature",
            "deliverable": "Feature is implemented and reviewed",
            "acceptance_criteria": ["Feature works"],
            "steps": ["execute", "security_review", "review"],
        }]
    })
    tasks = stage.spec.parser(payload, context)
    result = stage.finish(context, StageResult("planning", "pass", data=tasks))

    assert context.state.tasks[0].steps == [
        "execute", "security_review", "review"
    ]
    assert [item["name"] for item in result.next_steps] == [
        "execute", "security_review", "review"
    ]
    assert result.next_steps[-1]["_task_last"] is True


def test_plan_rejects_static_or_unknown_stage_name(tmp_path):
    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    context = _context(tmp_path, workflow)
    stage = create_stage(workflow[0])
    payload = json.dumps({
        "tasks": [{
            "title": "Bad plan",
            "description": "Try to call a static validator",
            "deliverable": "Invalid",
            "acceptance_criteria": ["Invalid"],
            "steps": ["execute", "validate_file"],
        }]
    })
    with pytest.raises(RunnerError, match="unavailable Stage: validate_file"):
        stage.spec.parser(payload, context)


def test_plan_rejects_task_without_write_stage_when_available(tmp_path):
    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    context = _context(tmp_path, workflow)
    stage = create_stage(workflow[0])
    payload = json.dumps({
        "tasks": [{
            "title": "Review-only non-work",
            "description": "Incorrectly skip implementation",
            "deliverable": "No project change",
            "acceptance_criteria": ["A writable task stage was used"],
            "steps": ["review"],
        }]
    })
    with pytest.raises(RunnerError, match="must include a write Stage"):
        stage.spec.parser(payload, context)


def test_registry_is_only_type_to_class():
    assert set(STAGE_REGISTRY) == {"base", "plan", "python"}
    assert all(isinstance(stage_class, type) for stage_class in STAGE_REGISTRY.values())


def test_new_stage_needs_class_registration_and_yaml_instance(tmp_path):
    register_stage("probe", ProbeStage)
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  probe_check:
    type: probe
    status: Probe
    value: configured
  validate:
    type: python
    validator: file
    status: Validate
flow:
  - probe_check
  - validate
""",
        encoding="utf-8",
    )
    try:
        stage = create_stage(load_workflow(workflow_file)[0])
    finally:
        STAGE_REGISTRY.pop("probe", None)
    assert isinstance(stage, ProbeStage)
    assert stage.spec.value == "configured"


def test_topology_uses_stage_type_and_validator_capability(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  plan:
    type: plan
    status: Plan
  execute:
    status: Execute
  review:
    status: Review
    result_handler: review
  gate:
    type: python
    validator: file
    status: Gate
flow: [plan, gate]
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    assert workflow_has_planning(workflow)
    assert workflow_validators(workflow) == (True, False)
    assert list(workflow[0]["planner_stages"]) == ["execute", "review"]

def test_custom_base_stage_loads_relative_instructions(tmp_path):
    (tmp_path / "task.md").write_text("Implement the report.", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  implement:
    status: Implement
    mode: write
    prompt: stages/workflow_prompt.md
    instructions_file: task.md
    retry: -1
  validate:
    type: python
    validator: file
    status: Validate
flow: [implement, validate]
""",
        encoding="utf-8",
    )
    definition = load_workflow(workflow_file)[0]
    stage = create_stage(definition)
    assert definition["instructions"] == "Implement the report."
    assert stage.spec.retry == -1


def test_restart_routing_belongs_to_flow_node_not_stage(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  repair:
    type: base
    status: Repair
  validate:
    type: python
    validator: file
    status: Validate
    restart_at: repair
flow: [repair, validate]
""",
        encoding="utf-8",
    )
    definition = load_workflow(workflow_file)[1]
    node = FlowNode.from_definition(definition)
    assert node.restart_at == "repair"
    assert not hasattr(node.stage, "restart_at")


@pytest.mark.parametrize(
    ("validator", "ai_prompt", "names"),
    [
        ("validator.py", "AI check", ["planning", "validate_file", "validate_ai"]),
        ("validator.py", "", ["planning", "validate_file"]),
        ("ai", "", ["planning", "validate_ai"]),
    ],
)
def test_validation_options_select_builtin_workflow(validator, ai_prompt, names):
    workflow = RunRequest(
        goal="goal", validator=validator, ai_validator_prompt=ai_prompt
    ).to_runtime_config().workflow
    assert _names(workflow) == names
    assert set(BUILTIN_WORKFLOWS) == {"mixed", "file", "ai"}


def test_builtin_workflow_yaml_lives_in_dedicated_folder():
    assert BUILTIN_WORKFLOW_DIR.name == "builtin"
    assert all(path.parent == BUILTIN_WORKFLOW_DIR for path in BUILTIN_WORKFLOWS.values())


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("stages: {}\nflow: []\n", "non-empty YAML array"),
        (
            "stages:\n  x:\n    type: missing\n    status: X\nflow: [x]\n",
            "unknown type",
        ),
        (
            "stages:\n  x:\n    status: X\n    nope: 1\n  v:\n    type: python\n    validator: file\n    status: V\nflow: [x, v]\n",
            "unknown options: nope",
        ),
        (
            "stages:\n  v:\n    validator: ai\n    status: V\n    runs: 1\n    required_passes: 2\nflow: [v]\n",
            "required_passes cannot exceed runs",
        ),
    ],
)
def test_invalid_workflow_is_rejected(tmp_path, body, message):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(body, encoding="utf-8")
    with pytest.raises(RunnerError, match=message):
        load_workflow(workflow_file)


def test_resume_runs_only_remaining_generated_steps(tmp_path):
    from runner.workflow.pipeline import Pipeline

    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    catalog = workflow[0]["planner_stages"]
    dynamic_steps = []
    for task_index in (1, 2):
        for step_index, name in enumerate(("execute", "review")):
            step = dict(catalog[name])
            step["_task_index"] = task_index
            step["_task_last"] = step_index == 1
            dynamic_steps.append(step)
    state = RunState(
        "run",
        "goal",
        str(tmp_path),
        tasks=[
            Task("t1", "one", "do", ["done"], "out", status="completed", steps=["execute", "review"]),
            Task("t2", "two", "do", ["done"], "out", steps=["execute", "review"]),
            Task("t3", "three", "do", ["done"], "out", steps=["execute", "review"]),
        ],
        current=1,
        workflow_position=0,
        dynamic_steps=dynamic_steps,
    )
    context = _context(tmp_path, workflow, state)

    class ResumeExecutor:
        def __init__(self):
            self.calls = []

        def run(self, stage, ctx, previous=None):
            self.calls.append(stage.name)
            return StageResult(stage.name, "pass")

    executor = ResumeExecutor()
    Pipeline(context, workflow).run(executor)

    assert executor.calls == [
        "execute", "review", "execute", "review", "validate_file"
    ]
    assert context.state.workflow_position == 2
    assert context.state.dynamic_steps == []
    assert context.state.current == 3

class RecordingExecutor:
    def __init__(self, workflow):
        self.calls = []
        self.catalog = workflow[0]["planner_stages"]

    def run(self, stage, ctx, previous=None):
        self.calls.append(stage.name)
        if stage.name == "planning":
            tasks = [
                Task(
                    f"t{i}", f"task {i}", "do", ["done"], "out",
                    steps=["execute", "review"],
                )
                for i in range(1, 4)
            ]
            ctx.state.tasks = tasks
            ctx.state.current = 0
            next_steps = []
            for task_index, task in enumerate(tasks):
                for step_index, name in enumerate(task.steps):
                    step = dict(self.catalog[name])
                    step["_task_index"] = task_index
                    step["_task_last"] = step_index == len(task.steps) - 1
                    next_steps.append(step)
            return StageResult(stage.name, "pass", data=tasks, next_steps=next_steps)
        return StageResult(stage.name, "pass")

def test_plan_generated_steps_run_in_order_for_each_task(tmp_path):
    from runner.workflow.pipeline import Pipeline

    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    context = _context(tmp_path, workflow)
    executor = RecordingExecutor(workflow)

    Pipeline(context, workflow).run(executor)

    assert executor.calls == [
        "planning",
        "execute", "review",
        "execute", "review",
        "execute", "review",
        "validate_file",
    ]
    assert context.state.current == 3
    assert context.state.dynamic_steps == []

def test_generic_stage_instances_can_be_reused_and_overridden(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  run_prompt:
    status: AI 正在執行 Prompt
    run_state: executing
    mode: write
    actor: executor
    track_changes: true


  review:
    status: AI 正在執行 Review
    run_state: reviewing
    mode: readonly
    actor: ai
    backend_mode: review
    parser: review
    result_status: completed

  validate_file:
    type: python
    validator: file
    status: 正在執行 File Validator
    run_state: validating
    mode: write
    actor: validator
    result_handler: validation

flow:
  - stage: run_prompt
    prompt: xxxxx.md

  - stage: review
    prompt: aaaa.md
    retry: 1
    skip: true

  - stage: run_prompt
    prompt: bbbb.md

  - stage: review
    prompt: cccc.md
    skip: false

  - validate_file
""",
        encoding="utf-8",
    )

    workflow = load_workflow(workflow_file)

    assert _names(workflow) == [
        "run_prompt", "review", "run_prompt", "review", "validate_file"
    ]
    assert workflow[0]["type"] == "base"
    assert workflow[0]["prompt"] == "xxxxx.md"
    assert workflow[1]["retry"] == 1
    assert workflow[1]["skip_on_error"] is True
    assert workflow[3]["skip_on_error"] is False
    assert workflow[-1]["type"] == "python"


def test_file_only_flow_completes_when_top_level_workflow_reaches_end(tmp_path):
    from runner.workflow.pipeline import Pipeline

    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    context = _context(tmp_path, workflow)
    context.state.workflow_position = 1

    class ValidatorExecutor:
        def run(self, stage, ctx, previous=None):
            return StageResult(stage.name, "pass", output="PASS")

    Pipeline(context, workflow).run(ValidatorExecutor())
    assert context.state.completed
    assert context.state.workflow_position == 2


def test_validator_failure_resume_uses_yaml_repair_plan(tmp_path):
    from runner.workflow.pipeline import Pipeline

    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    context = _context(tmp_path, workflow)
    context.state.workflow_position = 1
    context.set_stage = lambda stage, _detail: setattr(context.state, "stage", stage)
    handle_validation_result(
        context, StageResult("validate_file", "fail", output="broken")
    )
    flow = Pipeline(context, workflow)._initial_flow()
    assert flow[0]["name"] == "repair_plan"
    assert list(flow[0]["planner_stages"]) == ["execute", "review"]
    assert flow[1]["name"] == "validate_file"

def test_workflow_fingerprint_changes_with_yaml_semantics():
    workflow = load_workflow()
    changed = [dict(item) for item in workflow]
    changed[0]["retry"] = 3
    assert workflow_fingerprint(workflow) != workflow_fingerprint(changed)


def test_legacy_role_scope_metadata_is_not_part_of_new_schema(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  validate:
    type: python
    validator: file
    role: file_validation
    scope: run
    status: Validate
flow: [validate]
""",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="unknown options: role, scope"):
        load_workflow(workflow_file)


def test_resume_rebuilds_generated_steps_from_durable_task_plan(tmp_path):
    from runner.workflow.pipeline import Pipeline

    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    state = RunState(
        "run",
        "goal",
        str(tmp_path),
        tasks=[Task("t1", "repair", "do", ["done"], "out", steps=["execute", "review"])],
        current=0,
        workflow_position=1,
        stage="planning",
    )
    context = _context(tmp_path, workflow, state)

    class Executor:
        def __init__(self):
            self.calls = []

        def run(self, stage, ctx, previous=None):
            self.calls.append(stage.name)
            return StageResult(stage.name, "pass")

    executor = Executor()
    Pipeline(context, workflow).run(executor)
    assert executor.calls == ["execute", "review", "validate_file"]
    assert context.state.completed


def test_legacy_task_workflow_state_migrates_to_dynamic_steps(tmp_path):
    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    catalog = workflow[0]["planner_stages"]
    state = RunState.load({
        "run_id": "run",
        "goal": "goal",
        "project_root": str(tmp_path),
        "tasks": [
            {"id": "t1", "title": "one", "description": "do", "deliverable": "out", "acceptance_criteria": ["done"], "status": "completed"},
            {"id": "t2", "title": "two", "description": "do", "deliverable": "out", "acceptance_criteria": ["done"]},
        ],
        "current": 1,
        "workflow_position": 0,
        "task_workflow": [catalog["execute"], catalog["review"]],
    })
    assert [item["name"] for item in state.dynamic_steps] == ["execute", "review"]
    assert state.dynamic_steps[-1]["_task_index"] == 1
    assert state.dynamic_steps[-1]["_task_last"] is True


def test_base_type_is_default_and_can_be_explicit(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  implicit:
    status: Implicit
    prompt: one.md
  explicit:
    type: base
    status: Explicit
    prompt: two.md
  validate:
    type: python
    validator: file
    status: Validate
flow: [implicit, explicit, validate]
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    assert [item["type"] for item in workflow[:2]] == ["base", "base"]


def test_workflow_schema_has_only_stages_and_flow(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  validate:
    type: python
    validator: file
    status: Validate
workflows:
  unused: [validate]
flow: [validate]
""",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="only stages and flow"):
        load_workflow(workflow_file)


def test_multi_prompt_example_reuses_same_base_stage():
    example = Path(__file__).resolve().parents[1] / "examples" / "workflow_multi_prompt.yaml"
    workflow = load_workflow(example)
    prompts = [item.get("prompt") for item in workflow if item["name"] == "run_prompt"]
    assert prompts == ["prompts/step_a.md", "prompts/step_b.md", "prompts/step_c.md"]
    assert all(item["type"] == "base" for item in workflow if item["name"] == "run_prompt")


def test_skill_prompt_review_chain_example_uses_one_prompt_stage_with_skill_prefixes():
    example = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "workflows"
        / "skill_prompt_review_chain.yaml"
    )
    workflow = load_workflow(example)
    pairs = [
        (
            item["name"],
            Path(item["prompt"]).relative_to(example.parent).as_posix(),
        )
        for item in workflow
        if item["name"] != "validate_file"
    ]
    assert pairs == [
        ("run_prompt", "prompts/design.md"),
        ("review", "prompts/review_design.md"),
        ("run_prompt", "prompts/implementation.md"),
        ("review", "prompts/review_implementation.md"),
        ("run_prompt", "prompts/documentation.md"),
        ("review", "prompts/review_documentation.md"),
    ]
    assert {item["name"] for item in workflow} == {"run_prompt", "review", "validate_file"}
    for prompt in ("design.md", "implementation.md", "documentation.md"):
        text = (example.parent / "prompts" / prompt).read_text(encoding="utf-8")
        assert text.startswith("/skill-")


def test_workflow_examples_reference_existing_prompt_assets():
    for example in (Path(__file__).resolve().parents[1] / "examples" / "workflows").glob("*.yaml"):
        text = example.read_text(encoding="utf-8")
        import yaml

        data = yaml.safe_load(text)
        refs = [
            item
            for stage in data.get("stages", {}).values()
            for item in (stage.get("prompt"), stage.get("instructions_file"))
            if item
        ]
        refs.extend(
            item["prompt"]
            for item in data.get("flow", [])
            if isinstance(item, dict) and item.get("prompt")
        )
        assert refs, example
        for ref in refs:
            assert (example.parent / ref).is_file(), (example, ref)
