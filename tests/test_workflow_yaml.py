from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from runner.api import RunRequest
from runner.config.runtime import RuntimeConfig
from runner.errors import RunnerError
from runner.runtime.run_state import RunState, Task
from runner.workflow.loader import (
    BUILTIN_WORKFLOW_DIR,
    BUILTIN_WORKFLOWS,
    default_workflow_name,
    load_workflow,
    workflow_fingerprint,
    workflow_validators,
)
from runner.workflow.pipeline import FlowNode
from runner.workflow.registry import STAGE_REGISTRY, create_stage, register_stage
from runner.workflow.rules import handle_validation_result
from runner.workflow.stages.contracts import StageContext, StageResult
python = "{python}"
validator = "{validator}"
project_root = "{project_root}"
state_file = "{state_file}"
validator_args = "{validator_args}"



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


def test_default_workflow_plan_uses_static_task_scope():
    workflow = load_workflow()
    assert _names(workflow) == [
        "planning", "execute", "review", "validate_file", "validate_ai"
    ]
    assert [item.get("scope") for item in workflow] == [
        None, "task", "task", None, None
    ]
    assert "planner_stages" not in workflow[0]

def test_task_sop_explicitly_includes_new_stage(tmp_path):
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
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    status: Validate
flow:
  - planning
  - stage: execute
    scope: task
  - stage: security_review
    scope: task
  - stage: review
    scope: task
  - validate
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    assert _names(workflow) == [
        "planning", "execute", "security_review", "review", "validate"
    ]
    assert [item.get("scope") for item in workflow[1:4]] == ["task"] * 3

def test_plan_stage_generates_todos_only(tmp_path):
    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    context = _context(tmp_path, workflow)
    stage = create_stage(workflow[0])
    payload = json.dumps({
        "tasks": [{
            "title": "Secure feature",
            "description": "Implement the feature",
            "deliverable": "Feature is implemented",
            "acceptance_criteria": ["Feature works"],
        }]
    })
    tasks = stage.spec.parser(payload, context)
    result = stage.finish(context, StageResult("planning", "pass", data=tasks))

    assert result.data == tasks
    assert tasks[0].title == "Secure feature"
    assert not hasattr(tasks[0], "steps")
    assert not hasattr(result, "next_steps")

def test_plan_ignores_stage_topology_and_parses_todo_content(tmp_path):
    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    context = _context(tmp_path, workflow)
    stage = create_stage(workflow[0])
    payload = json.dumps({
        "tasks": [{
            "title": "Plan only work",
            "description": "Planner describes the work, not Stage names",
            "deliverable": "Done",
            "acceptance_criteria": ["Done"],
        }]
    })
    tasks = stage.spec.parser(payload, context)
    assert len(tasks) == 1
    assert tasks[0].title == "Plan only work"

def test_task_producer_does_not_require_task_scope(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  planning:
    type: plan
  validate:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
flow: [planning, validate]
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    assert _names(workflow) == ["planning", "execute", "review", "validate"]
    assert [item["name"] for item in workflow if item.get("scope") == "task"] == [
        "execute", "review"
    ]

def test_registry_is_only_type_to_class():
    assert set(STAGE_REGISTRY) == {"base", "task", "review", "ai_validator", "command", "plan"}
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
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
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


def test_topology_uses_stage_type_validator_and_task_scope(tmp_path):
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
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    status: Gate
flow:
  - plan
  - gate
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    assert any(item.get("type") == "plan" for item in workflow)
    assert workflow_validators(workflow) == (True, False)
    assert [item["name"] for item in workflow if item.get("scope") == "task"] == [
        "execute", "review"
    ]

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
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    status: Validate
flow: [implement, validate]
""",
        encoding="utf-8",
    )
    definition = load_workflow(workflow_file)[0]
    stage = create_stage(definition)
    assert definition["instructions"] == "Implement the report."
    assert stage.spec.retry == -1


def test_flow_node_label_is_not_allowed_in_reusable_stage_definition(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  implement:
    status: Execute
    label: Wrong place
  validate:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    status: Validate
flow: [implement, validate]
""",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="label belongs to flow nodes"):
        load_workflow(workflow_file)


def test_flow_node_label_is_routing_metadata_not_stage_option(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  implement:
    status: Execute
  validate:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    status: Validate
flow:
  - stage: implement
    label: Project Documentation
  - stage: validate
""",
        encoding="utf-8",
    )
    definition = load_workflow(workflow_file)[0]
    node = FlowNode.from_definition(definition)
    assert node.label == "Project Documentation"
    assert not hasattr(node.stage, "label")


@pytest.mark.parametrize("value", ["", "   ", 3, True])
def test_flow_node_label_must_be_non_empty_string(tmp_path, value):
    workflow_file = tmp_path / "workflow.yaml"
    rendered = repr(value) if not isinstance(value, str) else f'"{value}"'
    workflow_file.write_text(
        f"""
stages:
  implement:
    status: Execute
  validate:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    status: Validate
flow:
  - stage: implement
    label: {rendered}
  - stage: validate
""",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="label must be a non-empty string"):
        load_workflow(workflow_file)


def test_restart_routing_belongs_to_flow_node_not_stage(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  repair:
    type: base
    status: Repair
  validate:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
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
        ("validator.py", "AI check", ["planning", "execute", "review", "validate_file", "validate_ai"]),
        ("validator.py", "", ["planning", "execute", "review", "validate_file"]),
        ("ai", "", ["planning", "execute", "review", "validate_ai"]),
    ],
)
def test_validation_options_select_builtin_workflow(validator, ai_prompt, names):
    workflow = RunRequest(
        goal="goal", validator=validator, ai_validator_prompt=ai_prompt
    ).to_runtime_config().workflow
    assert _names(workflow) == names
    assert set(BUILTIN_WORKFLOWS) == {"mixed", "file", "ai"}


@pytest.mark.parametrize(
    ("validator", "ai_prompt", "workflow_name"),
    [
        ("validator.py", "", "file"),
        ("validator.py", "AI check", "mixed"),
        ("ai", "", "ai"),
        ("AI", "ignored for ai-only", "ai"),
    ],
)
def test_default_workflow_name_is_explicit(validator, ai_prompt, workflow_name):
    assert default_workflow_name(validator, ai_prompt) == workflow_name


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
            "stages:\n  x:\n    status: X\n    nope: 1\nflow: [x]\n",
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


def test_resume_runs_only_remaining_task_scoped_work(tmp_path):
    from runner.workflow.pipeline import Pipeline

    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    state = RunState(
        "run",
        "goal",
        str(tmp_path),
        tasks=[
            Task("t1", "one", "do", ["done"], "out", status="completed"),
            Task("t2", "two", "do", ["done"], "out"),
            Task("t3", "three", "do", ["done"], "out"),
        ],
        current=1,
        workflow_position=1,
        task_step=0,
    )
    context = _context(tmp_path, workflow, state)

    class ResumeExecutor:
        def __init__(self):
            self.calls = []

        def run(self, stage, ctx, previous=None, **kwargs):
            self.calls.append(stage.name)
            return StageResult(stage.name, "pass")

    executor = ResumeExecutor()
    Pipeline(context, workflow).run(executor)

    assert executor.calls == [
        "execute", "review", "execute", "review", "validate_file"
    ]
    assert context.state.workflow_position == len(workflow)
    assert context.state.task_step == 0
    assert context.state.current == 3

def test_plan_todos_run_same_task_scoped_sop_in_order(tmp_path):
    from runner.workflow.pipeline import Pipeline
    from runner.workflow.rules import reduce_result

    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    context = _context(tmp_path, workflow)

    class RecordingExecutor:
        def __init__(self):
            self.calls = []

        def run(self, stage, ctx, previous=None, **kwargs):
            self.calls.append(stage.name)
            if stage.name == "planning":
                tasks = [
                    Task(f"t{i}", f"task {i}", "do", ["done"], "out")
                    for i in range(1, 4)
                ]
                return reduce_result(
                    ctx, StageResult(stage.name, "pass", data=tasks, kind="tasks")
                )
            return StageResult(stage.name, "pass")

    executor = RecordingExecutor()
    Pipeline(context, workflow).run(executor)

    assert executor.calls == [
        "planning",
        "execute", "review",
        "execute", "review",
        "execute", "review",
        "validate_file",
    ]
    assert context.state.current == 3
    assert context.state.task_step == 0

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
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
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
    assert workflow[-1]["type"] == "command"


def test_file_only_flow_completes_when_top_level_workflow_reaches_end(tmp_path):
    from runner.workflow.pipeline import Pipeline

    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    context = _context(tmp_path, workflow)
    context.state.workflow_position = len(workflow) - 1

    class ValidatorExecutor:
        def run(self, stage, ctx, previous=None):
            return StageResult(stage.name, "pass", output="PASS")

    Pipeline(context, workflow).run(ValidatorExecutor())
    assert context.state.completed
    assert context.state.workflow_position == len(workflow)


def test_validator_failure_resume_uses_yaml_repair_plan(tmp_path):
    from runner.workflow.pipeline import Pipeline

    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    context = _context(tmp_path, workflow)
    context.state.workflow_position = len(workflow) - 1
    context.set_stage = lambda stage, _detail: setattr(context.state, "stage", stage)
    handle_validation_result(
        context, StageResult("validate_file", "fail", output="broken")
    )

    assert context.state.stage == "validator_failed"
    assert workflow[-1]["recover"][0]["name"] == "repair_plan"

def test_workflow_fingerprint_changes_with_yaml_semantics():
    workflow = load_workflow()
    changed = [dict(item) for item in workflow]
    changed[0]["retry"] = 3
    assert workflow_fingerprint(workflow) != workflow_fingerprint(changed)


def test_scope_belongs_to_flow_node_not_stage_definition(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  validate:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    scope: task
    status: Validate
flow: [validate]
""",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="scope belongs to flow nodes"):
        load_workflow(workflow_file)

def test_resume_restarts_current_todo_from_saved_task_step(tmp_path):
    from runner.workflow.pipeline import Pipeline

    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    state = RunState(
        "run",
        "goal",
        str(tmp_path),
        tasks=[Task("t1", "repair", "do", ["done"], "out")],
        current=0,
        workflow_position=1,
        task_step=1,
        stage="reviewing",
    )
    context = _context(tmp_path, workflow, state)

    class Executor:
        def __init__(self):
            self.calls = []

        def run(self, stage, ctx, previous=None, **kwargs):
            self.calls.append(stage.name)
            return StageResult(stage.name, "pass")

    executor = Executor()
    Pipeline(context, workflow).run(executor)
    assert executor.calls == ["review", "validate_file"]
    assert context.state.completed

def test_legacy_generated_workflow_state_is_ignored_safely(tmp_path):
    state = RunState.load({
        "run_id": "run",
        "goal": "goal",
        "project_root": str(tmp_path),
        "tasks": [
            {"id": "t1", "title": "one", "description": "do", "deliverable": "out", "acceptance_criteria": ["done"], "status": "completed", "steps": ["execute", "review"]},
            {"id": "t2", "title": "two", "description": "do", "deliverable": "out", "acceptance_criteria": ["done"], "steps": ["execute", "review"]},
        ],
        "current": 1,
        "workflow_position": 1,
        "dynamic_steps": [{"name": "review", "_task_index": 1}],
        "dynamic_index": 0,
    })
    assert state.current == 1
    assert state.task_step == 0
    assert not hasattr(state, "dynamic_steps")
    assert not hasattr(state.tasks[1], "steps")

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
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
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
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    status: Validate
workflows:
  unused: [validate]
flow: [validate]
""",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="only stages and flow"):
        load_workflow(workflow_file)


def test_multi_prompt_example_reuses_same_task_stage():
    example = Path(__file__).resolve().parents[1] / "examples" / "workflow_multi_prompt.yaml"
    workflow = load_workflow(example)
    prompts = [item.get("prompt") for item in workflow if item["name"] == "run_prompt"]
    assert prompts == ["prompts/step_a.md", "prompts/step_b.md", "prompts/step_c.md"]
    assert all(item["type"] == "task" for item in workflow if item["name"] == "run_prompt")


def test_skill_prompt_review_chain_example_uses_one_prompt_stage_with_skill_prefixes():
    example = (
        Path(__file__).resolve().parents[1]
        / "tool"
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
    assert all("result_handler" not in item for item in workflow if item["name"] == "review")
    assert [item["name"] for item in workflow[-1]["recover"]] == ["run_prompt", "review"]
    assert Path(workflow[-1]["recover"][0]["prompt"]).relative_to(example.parent).as_posix() == (
        "prompts/fix_validation.md"
    )
    for prompt in ("design.md", "implementation.md", "documentation.md"):
        text = (example.parent / "prompts" / prompt).read_text(encoding="utf-8")
        assert text.startswith("/skill-")


def test_workflow_yaml_examples_reference_existing_prompt_assets():
    def collect_refs(data):
        refs = []
        for stage in data:
            refs.extend(
                item
                for item in (stage.get("prompt"), stage.get("instructions_file"))
                if item
            )
            refs.extend(collect_refs(stage.get("recover", ())))
        return refs

    root = Path(__file__).resolve().parents[1]
    examples = sorted((root / "tool" / "workflows").glob("*.yaml"))
    for example in examples:
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
        refs.extend(collect_refs(load_workflow(example)))
        assert refs, example
        for ref in refs:
            path = Path(ref)
            if not path.is_absolute():
                path = example.parent / path
            assert path.is_file(), (example, ref)


def test_custom_workflow_resolves_local_continuation_prompt(tmp_path):
    workflow = tmp_path / "workflow.yaml"
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "full.md").write_text("full", encoding="utf-8")
    (skills / "continue.md").write_text("continue", encoding="utf-8")
    workflow.write_text(
        "stages:\n  work:\n    status: Work\n    prompt: skills/full.md\n    continuation_prompt: skills/continue.md\n  validate:\n    validator: ai\n    status: Validate\n    prompt: skills/full.md\n    parser: validation\n    result_status: validation\nflow: [work, validate]\n",
        encoding="utf-8",
    )
    flow = load_workflow(workflow)
    assert Path(flow[0]["prompt"]) == (skills / "full.md").resolve()
    assert Path(flow[0]["continuation_prompt"]) == (skills / "continue.md").resolve()


def test_flow_node_repeat_is_normalized(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text("""
stages:
  grill:
    status: Grill
  fix:
    status: Fix
  validate:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    status: Validate
flow:
  - stage: grill
    repeat: 3
    recover: [fix]
  - validate
""", encoding="utf-8")
    workflow = load_workflow(workflow_file)
    assert workflow[0]["repeat"] == 3


@pytest.mark.parametrize("value", [0, -1, True, "3"])
def test_flow_node_repeat_must_be_positive_integer(tmp_path, value):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(f"""
stages:
  grill:
    status: Grill
  fix:
    status: Fix
  validate:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    status: Validate
flow:
  - stage: grill
    repeat: {str(value).lower() if isinstance(value, bool) else (repr(value) if isinstance(value, str) else value)}
    recover: [fix]
  - validate
""", encoding="utf-8")
    with pytest.raises(RunnerError, match="repeat must be a positive integer"):
        load_workflow(workflow_file)


def test_flow_node_repeat_requires_recover(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text("""
stages:
  grill:
    status: Grill
  validate:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    status: Validate
flow:
  - stage: grill
    repeat: 3
  - validate
""", encoding="utf-8")
    with pytest.raises(RunnerError, match="repeat requires recover"):
        load_workflow(workflow_file)


def test_base_stage_status_uses_simple_default_when_omitted(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """stages:
  work:
    actor: ai
    prompt: work.md
  final:
    type: ai_validator
    validator: ai
flow:
  - work
  - final
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    stage = create_stage(workflow[0])
    assert stage.status == "AI Stage"




def test_builtin_review_owns_semantic_fresh_default():
    workflow = load_workflow(BUILTIN_WORKFLOWS["file"])
    review = next(item for item in workflow if item["name"] == "review")
    assert "fresh_after_same_failures" not in review
    stage = create_stage(review)
    assert stage.semantic_failure_threshold == 2

def test_flow_node_fresh_after_same_failures_is_normalized(tmp_path):
    path = tmp_path / "workflow.yaml"
    path.write_text(
        """
stages:
  review:
    status: Review
    prompt: review.md
  fix:
    status: Fix
    mode: write
  validate:
    validator: ai
    status: Validate
    prompt: validate.md
    parser: validation
    result_status: validation
flow:
  - stage: review
    fresh_after_same_failures: 2
    recover: [fix]
  - validate
""",
        encoding="utf-8",
    )
    workflow = load_workflow(path)
    assert workflow[0]["fresh_after_same_failures"] == 2


@pytest.mark.parametrize("value", [0, -1, True, "2"])
def test_fresh_after_same_failures_must_be_positive_integer(tmp_path, value):
    path = tmp_path / "workflow.yaml"
    encoded = str(value).lower() if isinstance(value, bool) else repr(value) if isinstance(value, str) else value
    path.write_text(
        f"""
stages:
  review:
    status: Review
    prompt: review.md
  fix:
    status: Fix
    mode: write
  validate:
    validator: ai
    status: Validate
    prompt: validate.md
    parser: validation
    result_status: validation
flow:
  - stage: review
    fresh_after_same_failures: {encoded}
    recover: [fix]
  - validate
""",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="fresh_after_same_failures must be a positive integer"):
        load_workflow(path)


def test_command_stage_can_produce_tasks_without_plan(tmp_path):
    import sys
    from runner.workflow.pipeline import Pipeline
    from runner.workflow.stages.executor import StageExecutor
    from runner.plugins.contracts import HookChain

    producer = tmp_path / "produce.py"
    producer.write_text(
        "import json\nprint(json.dumps({'tasks':["
        "{'title':'A','description':'a','deliverable':'a','acceptance_criteria':['a']},"
        "{'title':'B','description':'b','deliverable':'b','acceptance_criteria':['b']}]}))\n",
        encoding="utf-8",
    )
    worker = tmp_path / "work.py"
    worker.write_text(
        "from pathlib import Path\n"
        "p=Path('count.txt')\n"
        "p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\n",
        encoding="utf-8",
    )
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        f"""
stages:
  produce:
    type: command
    command: ["{python}", "produce.py"]
    produces: tasks
  work:
    type: command
    command: [{json.dumps(sys.executable)}, {json.dumps(str(worker))}]
flow:
  - produce
  - stage: work
    scope: task
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    context = _context(tmp_path, workflow)
    context.config.workflow_explicit = True
    context.validator_is_ai = False

    Pipeline(context, workflow).run(StageExecutor(HookChain()))

    assert [task.title for task in context.state.tasks] == ["A", "B"]
    assert context.state.current == 2
    assert context.state.completed
    assert (tmp_path / "count.txt").read_text() == "2"


def test_generic_workflow_does_not_require_plan_or_validator(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  prepare:
    type: command
    command: [python, -c, "print('ok')"]
flow: [prepare]
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    assert _names(workflow) == ["prepare"]
    assert workflow_validators(workflow) == (False, False)
    assert all(item.get("type") != "plan" for item in workflow)


def test_task_scope_without_tasks_fails_at_runtime_not_schema(tmp_path):
    from runner.workflow.pipeline import Pipeline
    from runner.workflow.stages.executor import StageExecutor
    from runner.plugins.contracts import HookChain

    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  work:
    type: command
    command: [python, -c, "print('ok')"]
flow:
  - stage: work
    scope: task
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    with pytest.raises(RunnerError, match="requires tasks from an earlier Stage or input"):
        Pipeline(_context(tmp_path, workflow), workflow).run(StageExecutor(HookChain()))


def test_explicit_workflow_request_does_not_require_validator(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  work:
    type: command
    command: [python, -c, "print('ok')"]
flow: [work]
""",
        encoding="utf-8",
    )
    request = RunRequest(
        goal="run generic workflow",
        project_root=str(tmp_path),
        workflow_file=str(workflow_file),
    )
    config = request.normalized_config()
    assert config.validator is None
    assert config.workflow_explicit is True


def test_simplified_plan_flow_keeps_legacy_normalized_fingerprint(tmp_path):
    simplified = tmp_path / "simplified.yaml"
    explicit = tmp_path / "explicit.yaml"
    stages = """
stages:
  planning:
    type: plan
  execute:
    type: task
  review:
    type: review
    recover: [repair]
  repair:
    type: task
  validate:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
"""
    simplified.write_text(
        stages + """
flow:
  - planning
  - validate
""",
        encoding="utf-8",
    )
    explicit.write_text(
        stages + """
flow:
  - planning
  - stage: execute
    scope: task
  - stage: review
    scope: task
  - validate
""",
        encoding="utf-8",
    )

    simplified_flow = load_workflow(simplified)
    explicit_flow = load_workflow(explicit)

    assert simplified_flow == explicit_flow
    assert workflow_fingerprint(simplified_flow) == workflow_fingerprint(explicit_flow)
