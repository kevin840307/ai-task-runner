from __future__ import annotations

from pathlib import Path

import pytest

from runner.config.runtime import RuntimeConfig
from runner.errors import RunnerError
from runner.runtime.run_state import RunState, StateStore
from runner.script import build_script_item_config, execute_script, load_yaml_script, select_script_workflow


def base_config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        project_root=str(tmp_path),
        work_dir=".ai-task-runner",
        script=str(tmp_path / "tasks.yaml"),
        goal="",
        validator=None,
        final_ai_validations=1,
        final_ai_required_passes=1,
        stage_retries=-1,
        retry_delay=5,
        retry_max_delay=300,
    )


def test_yaml_item_project_root_defaults_to_outer_root(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text("- prompt: old\n  validator: ai\n", encoding="utf-8")

    child = build_script_item_config(
        base_config(tmp_path),
        load_yaml_script(script)[0],
        1,
    )

    assert Path(child.project_root) == tmp_path.resolve()
    assert Path(child.work_dir) == Path(".ai-task-runner") / "script" / "001"


def test_yaml_item_project_root_resolves_from_outer_root(tmp_path):
    project = tmp_path / "examples" / "one"
    project.mkdir(parents=True)
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: one\n  project_root: examples/one\n  validator: ai\n",
        encoding="utf-8",
    )

    child = build_script_item_config(
        base_config(tmp_path),
        load_yaml_script(script)[0],
        1,
    )

    assert Path(child.project_root) == project.resolve()


def test_yaml_goal_file_is_loaded_relative_to_script(tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    goal = prompts / "goal.md"
    goal.write_text("build from file\n", encoding="utf-8")
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- goal_file: prompts/goal.md\n  validator: ai\n",
        encoding="utf-8",
    )

    item = load_yaml_script(script)[0]
    child = build_script_item_config(base_config(tmp_path), item, 1)

    assert item["goal"] == "build from file"
    assert Path(item["goal_file"]) == goal.resolve()
    assert child.goal == "build from file"


def test_yaml_goal_file_and_inline_prompt_are_mutually_exclusive(tmp_path):
    (tmp_path / "goal.md").write_text("file goal", encoding="utf-8")
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: inline\n  goal_file: goal.md\n  validator: ai\n",
        encoding="utf-8",
    )

    with pytest.raises(RunnerError, match="either prompt or goal_file"):
        load_yaml_script(script)


def test_yaml_item_workflow_precedence_is_item_then_outer_then_default(tmp_path):
    config = base_config(tmp_path)
    config.workflow = [{"name": "outer"}]
    config.workflow_explicit = True

    workflow, explicit = select_script_workflow(
        config,
        {"validator": "ai", "workflow": [{"name": "item"}]},
        "",
    )
    assert workflow == [{"name": "item"}]
    assert explicit is True

    workflow, explicit = select_script_workflow(config, {"validator": "ai"}, "")
    assert workflow == [{"name": "outer"}]
    assert explicit is True

    config.workflow_explicit = False
    workflow, explicit = select_script_workflow(
        config,
        {"validator": "validator.py"},
        "",
    )
    assert [stage["name"] for stage in workflow] == [
        "planning",
        "execute",
        "review",
        "validate_file",
    ]
    assert explicit is False


def test_yaml_runtime_overrides_match_current_run_request_contract(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        """
- prompt: build
  validator: ai
  backend: qwen
  command: custom-qwen
  sandbox: false
  agent_args: [--agent-extra, "yes"]
  validator_args: [--fab, FAB23]
  protect_files: [locked.txt]
  validator_timeout: 31
  agent_timeout: 41
  planning_timeout: 51
  agent_idle_after_change_timeout: 61
  watchdog_interval: 2.5
  worker_hang_timeout: 601
  stage_retries: -1
  retry_delay: 7
  retry_max_delay: 90
  ai_validator_count: 3
  ai_validator_required_passes: 2
  ai_validator_yolo: true
  readonly_safety: observe
""",
        encoding="utf-8",
    )

    child = build_script_item_config(
        base_config(tmp_path),
        load_yaml_script(script)[0],
        1,
    )

    assert child.backend == "qwen"
    assert child.command == "custom-qwen"
    assert child.sandbox is False
    assert child.agent_args == ["--agent-extra", "yes"]
    assert child.validator_args == ["--fab", "FAB23"]
    assert child.protect_files == ["locked.txt"]
    assert child.validator_timeout == 31
    assert child.agent_timeout == 41
    assert child.planning_timeout == 51
    assert child.agent_idle_after_change_timeout == 61
    assert child.watchdog_interval == 2.5
    assert child.worker_hang_timeout == 601
    assert child.stage_retries == -1
    assert child.retry_delay == 7
    assert child.retry_max_delay == 90
    assert child.final_ai_validations == 3
    assert child.final_ai_required_passes == 2
    assert child.ai_validator_yolo is True
    assert child.readonly_safety == "observe"


def test_yaml_rejects_removed_retry_fields(tmp_path):
    removed = (
        "max_attempts",
        "max_cycles",
        "review_retries",
        "api_wait_timeout",
        "retry_wait",
        "retry_max_wait",
    )
    for field in removed:
        script = tmp_path / "tasks.yaml"
        script.write_text(
            f"- prompt: build\n  validator: ai\n  {field}: 2\n",
            encoding="utf-8",
        )
        item = load_yaml_script(script)[0]
        child = build_script_item_config(base_config(tmp_path), item, 1)
        assert not hasattr(child, field)


def test_execute_script_uses_distinct_item_roots_and_stops_on_failure(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    script = tmp_path / "tasks.yaml"
    script.write_text(
        """
- prompt: first
  project_root: a
  validator: ai
- prompt: second
  project_root: b
  validator: ai
""",
        encoding="utf-8",
    )
    config = base_config(tmp_path)
    config.script = str(script)
    seen = []

    def execute_one(child):
        seen.append(child.script_index)
        root = Path(child.project_root)
        completed = child.script_index == 1
        StateStore(root, root / child.work_dir).save(
            RunState(
                run_id=f"run-{child.script_index}",
                goal=child.goal,
                project_root=str(root),
                completed=completed,
                stage="completed" if completed else "executing",
            )
        )
        return 0

    assert execute_script(config, execute_one) == 1
    assert seen == [1, 2]


def test_execute_script_multi_item_completion_uses_same_runtime_state_contract(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: first\n  validator: ai\n"
        "- prompt: second\n  validator: ai\n",
        encoding="utf-8",
    )
    config = base_config(tmp_path)
    config.script = str(script)
    seen = []

    def execute_one(child):
        seen.append((child.script_index, child.work_dir))
        root = Path(child.project_root)
        StateStore(root, root / child.work_dir).save(
            RunState(
                run_id=f"run-{child.script_index}",
                goal=child.goal,
                project_root=str(root),
                completed=True,
                stage="completed",
            )
        )
        return 0

    assert execute_script(config, execute_one) == 0
    assert [index for index, _ in seen] == [1, 2]
    assert seen[0][1].endswith("script/001") or seen[0][1].endswith("script\\001")
    assert seen[1][1].endswith("script/002") or seen[1][1].endswith("script\\002")


def test_yaml_inline_workflow_is_normalized(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        """
- prompt: validate only
  workflow:
    stages:
      check:
        type: command
        command: [python, -c, "print('ok')"]
    flow: [check]
""",
        encoding="utf-8",
    )

    item = load_yaml_script(script)[0]

    assert item["validator"] is None
    assert [node["name"] for node in item["workflow"]] == ["check"]
