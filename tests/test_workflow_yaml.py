from __future__ import annotations

import sys
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
from runner.workflow.rules import (
    flow_definition,
    handle_validation_result,
    initial_flow,
)
from runner.workflow.stages.contracts import StageContext, StageResult


class FakeAI:
    session_id = ""


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
    workflow = RunRequest(
        goal="goal",
        validator=validator,
        ai_validator_prompt=ai_prompt,
    ).to_runtime_config().workflow

    assert [stage["name"] for stage in workflow] == names
    assert set(BUILTIN_WORKFLOWS) == {"mixed", "file", "ai"}


def test_custom_workflow_loads_relative_prompts_and_stage_options(tmp_path):
    (tmp_path / "implement.md").write_text("Implement the report.", encoding="utf-8")
    (tmp_path / "review.md").write_text("Check the report.", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
- planning
- stage: run_prompt
  prompt: implement.md
  retry: -1
- stage: review
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
        "run_prompt",
        "review",
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
                "- planning\n- stage: run_prompt\n  prompt: missing.md\n"
                "- validate_file\n- validate_ai\n"
            ),
            "prompt not found",
        ),
        (
            (
                "- stage: run_prompt\n  id: unsupported\n  prompt: task.md\n"
                "- validate_file\n"
            ),
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
            "- planning\n- validate_ai\n- validate_file\n",
            "validate_file must run before validate_ai",
        ),
        (
            (
                "- planning\n- stage: run_prompt\n  prompt: empty.md\n"
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
        "- planning\n- stage: run_prompt\n  prompt: after.md\n"
        "- validate_file\n- validate_ai\n",
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
        "run_prompt",
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
- stage: run_prompt
  prompt: a.md
- stage: review
  prompt: b.md
  retry: 1
  skip: true
- stage: run_prompt
  prompt: c.md
- stage: review
  prompt: d.md
  skip: false
- validate_file
""",
        encoding="utf-8",
    )

    workflow = load_workflow(workflow_file)

    assert [stage["name"] for stage in workflow] == [
        "run_prompt",
        "review",
        "run_prompt",
        "review",
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
        "- stage: run_prompt\n  prompt: prompt.md\n- validate_file\n",
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
        "run_prompt",
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
        "- planning\n- stage: run_prompt\n  prompt: after.md\n"
        "- validate_file\n- validate_ai\n",
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
        "run_prompt",
        "validate_file",
        "validate_ai",
    ]
    assert context.state.workflow_position == len(workflow)


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
        "- planning\n- stage: run_prompt\n  prompt: prompt.md\n"
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
- stage: run_prompt
  prompt: finish.md
- stage: review
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
