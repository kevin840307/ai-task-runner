from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from runner.api import RunRequest, run
from runner.config import RuntimeConfig
from runner.errors import RunnerError
from runner.runtime.run_state import RunState, StateStore, Task
from runner.script_loader import load_yaml_script
from runner.script_runner import build_script_item_config
from runner.task_runner import TaskRunner
from runner.workflow.loader import (
    BUILTIN_WORKFLOWS,
    load_workflow,
    workflow_fingerprint,
)
from runner.workflow.pipeline import Pipeline
from runner.workflow.registry import (
    STAGE_REGISTRY,
    StageRegistration,
    create_stage,
    register_stage,
)
from runner.workflow.rules import (
    apply_workflow_restart,
    flow_definition,
    handle_validation_result,
    initial_flow,
)
from runner.workflow.stages.contracts import StageContext, StageResult


class FakeAI:
    session_id = ""


@dataclass(frozen=True)
class RegistryProbeSpec:
    name: str
    status: str
    value: str = "default"


class RegistryProbeStage:
    def __init__(self, spec: RegistryProbeSpec):
        self.spec = spec


ROOT = Path(__file__).resolve().parents[1]


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


def test_default_workflow_preserves_existing_stage_order():
    workflow = load_workflow()

    assert [item["name"] for item in workflow] == [
        "planning",
        "validate_file",
        "validate_ai",
    ]


def test_new_stage_needs_only_class_registration_and_workflow_entry(tmp_path):
    registration = StageRegistration(
        name="registry_probe",
        stage_class="test_workflow_yaml:RegistryProbeStage",
        spec_class="test_workflow_yaml:RegistryProbeSpec",
        defaults={"status": "Probe"},
        options=frozenset({"value"}),
    )
    register_stage(registration)
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        "- stage: registry_probe\n  value: configured\n- validate_file\n",
        encoding="utf-8",
    )
    try:
        definition = load_workflow(workflow_file)[0]
        stage = create_stage(definition)
    finally:
        STAGE_REGISTRY.pop("registry_probe", None)

    assert isinstance(stage, RegistryProbeStage)
    assert stage.spec.value == "configured"


def test_ai_stage_defaults_are_kept_until_yaml_overrides_them(tmp_path):
    (tmp_path / "prompt.md").write_text("Check output.", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        "- stage: ai\n  mode: review\n  prompt: prompt.md\n- validate_file\n",
        encoding="utf-8",
    )
    default_stage = create_stage(load_workflow(workflow_file)[0])
    workflow_file.write_text(
        "- stage: ai\n  mode: review\n  prompt: prompt.md\n"
        "  retry: -1\n  skip: true\n- validate_file\n",
        encoding="utf-8",
    )
    overridden_stage = create_stage(load_workflow(workflow_file)[0])

    assert default_stage.spec.retry is None
    assert default_stage.spec.skip_on_error is False
    assert overridden_stage.spec.retry == -1
    assert overridden_stage.spec.skip_on_error is True


def test_restart_at_is_a_global_yaml_override(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        "- planning\n- stage: validate_file\n  restart_at: 1\n",
        encoding="utf-8",
    )

    stage = create_stage(load_workflow(workflow_file)[1])

    assert stage.restart_at == 1


@pytest.mark.parametrize(
    ("validator", "ai_prompt", "names"),
    [
        ("validator.py", "AI check", ["planning", "validate_file", "validate_ai"]),
        ("validator.py", "", ["planning", "validate_file"]),
        ("ai", "", ["planning", "validate_ai"]),
    ],
)
def test_cli_validation_options_select_a_builtin_workflow(
    validator,
    ai_prompt,
    names,
):
    workflow = (
        RunRequest(
            goal="goal",
            validator=validator,
            ai_validator_prompt=ai_prompt,
        )
        .to_runtime_config()
        .workflow
    )

    assert [stage["name"] for stage in workflow] == names
    assert set(BUILTIN_WORKFLOWS) == {"mixed", "file", "ai"}


def test_custom_workflow_loads_relative_prompts_and_stage_options(tmp_path):
    (tmp_path / "implement.md").write_text("Implement the report.", encoding="utf-8")
    (tmp_path / "review.md").write_text("Check the report.", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
- planning
- stage: ai
  prompt: implement.md
  retry: -1
- stage: ai
  mode: review
  prompt: review.md
  retry: 1
  skip: true
- validate_file
- stage: validate_ai
  runs: 3
  required_passes: 2
""",
        encoding="utf-8",
    )

    workflow = load_workflow(workflow_file)

    assert [item["name"] for item in workflow] == [
        "planning",
        "ai",
        "ai",
        "validate_file",
        "validate_ai",
    ]
    assert workflow[1]["instructions"] == "Implement the report."
    assert workflow[1]["retry"] == -1
    assert workflow[2]["skip_on_error"] is True
    assert workflow[4]["runs"] == 3
    assert workflow[4]["required_passes"] == 2


def test_validate_file_accepts_explicit_retry(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        "- planning\n- stage: validate_file\n  retry: -1\n- validate_ai\n",
        encoding="utf-8",
    )

    workflow = load_workflow(workflow_file)

    assert workflow[1]["retry"] == -1
    assert "retry_attr" not in workflow[1]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("- planning\n- unknown\n- validate_file\n- validate_ai\n", "is unknown"),
        (
            (
                "- planning\n- stage: ai\n  prompt: missing.md\n"
                "- validate_file\n- validate_ai\n"
            ),
            "prompt not found",
        ),
        (
            ("- stage: ai\n  id: unsupported\n  prompt: task.md\n- validate_file\n"),
            "unknown options: id",
        ),
        (
            (
                "- planning\n- validate_file\n- stage: validate_ai\n"
                "  runs: 1\n  required_passes: 2\n"
            ),
            "required_passes cannot exceed runs",
        ),
        (
            "- planning\n- stage: validate_file\n  restart_at: 0\n",
            "restart_at must be a positive integer",
        ),
        (
            "- stage: ai\n  prompt: task.md\n  restart_at: 2\n- validate_file\n",
            "restart_at must reference stage 1..1",
        ),
        (
            "- planning\n- validate_ai\n- validate_file\n",
            "validate_file must run before validate_ai",
        ),
        (
            (
                "- planning\n- stage: ai\n  prompt: empty.md\n"
                "- validate_file\n- validate_ai\n"
            ),
            "prompt must not be empty",
        ),
    ],
)
def test_invalid_workflow_is_rejected(tmp_path, body, message):
    (tmp_path / "task.md").write_text("task", encoding="utf-8")
    (tmp_path / "empty.md").write_text("", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(body, encoding="utf-8")

    with pytest.raises(RunnerError, match=message):
        load_workflow(workflow_file)


def test_resume_runs_pending_planning_children_before_workflow_tail(tmp_path):
    (tmp_path / "after.md").write_text("Finalize output.", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        "- planning\n- stage: ai\n  prompt: after.md\n- validate_file\n- validate_ai\n",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    state = RunState(
        "run",
        "goal",
        str(tmp_path),
        tasks=[Task("c01-t001", "Task", "Do it", ["done"], "output")],
        workflow_position=1,
    )

    flow = initial_flow(_context(tmp_path, workflow, state))

    assert [item["name"] for item in flow[0][0]] == ["execute", "review"]
    assert [item["name"] for item in flow[1:]] == [
        "ai",
        "validate_file",
        "validate_ai",
    ]


@pytest.mark.parametrize(
    "body",
    [
        "- planning\n- validate_file\n- validate_ai\n",
        "- planning\n- validate_file\n",
        "- planning\n- validate_ai\n",
        "- validate_file\n",
        "- validate_ai\n",
    ],
)
def test_supported_validation_topologies(tmp_path, body):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(body, encoding="utf-8")

    assert load_workflow(workflow_file)


def test_repeated_generic_stages_need_only_prompts(tmp_path):
    for name in ("a.md", "b.md", "c.md", "d.md"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
- stage: ai
  prompt: a.md
- stage: ai
  mode: review
  prompt: b.md
  retry: 1
  skip: true
- stage: ai
  prompt: c.md
- stage: ai
  mode: review
  prompt: d.md
  skip: false
- validate_file
""",
        encoding="utf-8",
    )

    workflow = load_workflow(workflow_file)

    assert [stage["name"] for stage in workflow] == [
        "ai",
        "ai",
        "ai",
        "ai",
        "validate_file",
    ]


def test_file_only_validation_pass_completes_the_run(tmp_path):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text("- planning\n- validate_file\n", encoding="utf-8")
    workflow = load_workflow(workflow_file)
    context = _context(tmp_path, workflow)

    result = handle_validation_result(
        context,
        StageResult("validate_file", "pass", output="PASS"),
    )

    assert result.complete
    assert context.state.completed


def test_validation_failure_restarts_workflow_without_planning(tmp_path):
    (tmp_path / "prompt.md").write_text("Fix the result.", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        "- stage: ai\n  prompt: prompt.md\n- validate_file\n",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    context = _context(tmp_path, workflow)

    result = handle_validation_result(
        context,
        StageResult("validate_file", "fail", output="still broken"),
    )

    assert result.replace_remaining
    assert [stage["name"] for stage in result.next_flow] == [
        "ai",
        "validate_file",
    ]


@pytest.mark.parametrize("status", ["fail", "replan"])
def test_failure_restarts_at_configured_workflow_position(tmp_path, status):
    (tmp_path / "prompt.md").write_text("Fix the result.", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        "- planning\n- stage: ai\n  prompt: prompt.md\n"
        "- stage: validate_file\n  restart_at: 2\n",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    context = _context(tmp_path, workflow)
    context.set_stage = lambda stage, _detail: setattr(context.state, "stage", stage)

    result = handle_validation_result(
        context,
        StageResult(
            "validate_file",
            status,
            output="still broken",
            restart_at=2,
        ),
    )
    result = apply_workflow_restart(context, result)

    assert result.replace_remaining
    assert [stage["name"] for stage in result.next_flow] == ["ai", "validate_file"]
    assert context.state.stage == "workflow_restart"
    assert context.state.workflow_position == 1
    assert [stage["name"] for stage in initial_flow(context)] == [
        "ai",
        "validate_file",
    ]


@pytest.mark.parametrize(
    ("body", "validator", "ai_prompt", "message"),
    [
        (
            "- planning\n- validate_file\n",
            "ai",
            "",
            "requires validate_ai",
        ),
        (
            "- planning\n- validate_ai\n",
            "validator.py",
            "",
            "requires validate_file",
        ),
        (
            "- planning\n- validate_file\n",
            "validator.py",
            "AI check",
            "requires validate_ai",
        ),
    ],
)
def test_runtime_rejects_workflow_that_omits_a_configured_gate(
    tmp_path,
    body,
    validator,
    ai_prompt,
    message,
):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(body, encoding="utf-8")
    config = RuntimeConfig(
        goal="goal",
        project_root=str(tmp_path),
        validator=validator,
        ai_validator_prompt=ai_prompt,
        workflow=load_workflow(workflow_file),
    )

    with pytest.raises(ValueError, match=message):
        config.validate()


def test_pipeline_runs_planning_children_before_next_top_level_stage(tmp_path):
    (tmp_path / "after.md").write_text("Finalize output.", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        "- planning\n- stage: ai\n  prompt: after.md\n- validate_file\n- validate_ai\n",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    context = _context(tmp_path, workflow)

    class Executor:
        def __init__(self):
            self.names = []

        def run(self, stage, ctx, previous=None):
            self.names.append(stage.name)
            if stage.name == "planning":
                return StageResult(
                    stage.name,
                    "pass",
                    next_flow=tuple(flow_definition("todo")),
                )
            return StageResult(
                stage.name,
                "pass",
                complete=stage.name == "validate_ai",
            )

    executor = Executor()
    Pipeline(context, workflow).run(executor)

    assert executor.names == [
        "planning",
        "execute",
        "review",
        "ai",
        "validate_file",
        "validate_ai",
    ]
    assert context.state.workflow_position == len(workflow)


def test_pipeline_applies_restart_at_without_stage_specific_routing(tmp_path):
    (tmp_path / "prompt.md").write_text("Fix the result.", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        "- stage: ai\n  prompt: prompt.md\n- stage: validate_file\n  restart_at: 1\n",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    context = _context(tmp_path, workflow)
    context.set_stage = lambda stage, _detail: setattr(context.state, "stage", stage)

    class Executor:
        def __init__(self):
            self.names = []
            self.failed = False

        def run(self, stage, ctx, previous=None):
            self.names.append(stage.name)
            if stage.name == "validate_file" and not self.failed:
                self.failed = True
                return StageResult(stage.name, "fail", restart_at=1)
            return StageResult(
                stage.name,
                "pass",
                complete=stage.name == "validate_file",
            )

    executor = Executor()
    Pipeline(context, workflow).run(executor)

    assert executor.names == ["ai", "validate_file", "ai", "validate_file"]
    assert context.state.completed


def test_workflow_fingerprint_changes_with_semantics():
    workflow = load_workflow()
    changed = [dict(item) for item in workflow]
    changed[0]["retry"] = 3

    assert workflow_fingerprint(workflow) != workflow_fingerprint(changed)


def test_resume_rejects_a_different_workflow(tmp_path):
    work = tmp_path / ".ai-task-runner"
    state = RunState(
        "run",
        "goal",
        str(tmp_path),
        workflow_fingerprint=workflow_fingerprint(load_workflow()),
    )
    StateStore(tmp_path, work).save(state)
    (tmp_path / "prompt.md").write_text("Do more.", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        "- planning\n- stage: ai\n  prompt: prompt.md\n"
        "- validate_file\n- validate_ai\n",
        encoding="utf-8",
    )
    config = RuntimeConfig(
        project_root=str(tmp_path),
        validator="ai",
        resume=True,
        workflow=load_workflow(workflow_file),
    )

    with pytest.raises(RunnerError, match="resume workflow differs"):
        TaskRunner(config)


def test_yaml_list_item_uses_its_relative_workflow(tmp_path):
    (tmp_path / "workflow.yaml").write_text(
        "- planning\n- validate_file\n- validate_ai\n",
        encoding="utf-8",
    )
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: build\n  validator: ai\n  workflow_file: workflow.yaml\n",
        encoding="utf-8",
    )
    item = load_yaml_script(script)[0]
    parent = RuntimeConfig(
        project_root=str(tmp_path),
        script=str(script),
        validator=None,
    )

    child = build_script_item_config(parent, item, 1)

    assert [stage["name"] for stage in child.workflow] == [
        "planning",
        "validate_file",
        "validate_ai",
    ]
    assert child.workflow is item["workflow"]
    assert child.workflow_explicit is True


@pytest.mark.parametrize(
    ("validator", "ai_prompt", "names"),
    [
        ("validator.py", "AI check", ["planning", "validate_file", "validate_ai"]),
        ("validator.py", "", ["planning", "validate_file"]),
        ("ai", "", ["planning", "validate_ai"]),
    ],
)
def test_yaml_list_item_selects_its_own_default_workflow(
    tmp_path,
    validator,
    ai_prompt,
    names,
):
    script = tmp_path / "tasks.yaml"
    validator_line = f"  validator: {validator}\n"
    ai_line = f"  ai_validator_prompt: {ai_prompt}\n" if ai_prompt else ""
    script.write_text(
        "- prompt: build\n" + validator_line + ai_line,
        encoding="utf-8",
    )
    item = load_yaml_script(script)[0]
    parent = RuntimeConfig(project_root=str(tmp_path), script=str(script))

    child = build_script_item_config(parent, item, 1)

    assert [stage["name"] for stage in child.workflow] == names
    assert child.workflow_explicit is False


def test_custom_workflow_runs_generated_children_then_top_level_stages(tmp_path):
    (tmp_path / "finish.md").write_text("Ensure done.txt exists.", encoding="utf-8")
    (tmp_path / "review.md").write_text("Verify done.txt exists.", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
- planning
- stage: ai
  prompt: finish.md
- stage: ai
  mode: review
  prompt: review.md
- validate_ai
""",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{ROOT / "tests/fake_agent.py"}"'

    result = run(
        RunRequest(
            goal="Create done.txt",
            project_root=str(tmp_path),
            workflow_file=str(workflow_file),
            validator="ai",
            backend="qwen",
            command=command,
            retry_delay=0,
        )
    )

    assert result.completed
    assert result.states[0]["workflow_position"] == 4
