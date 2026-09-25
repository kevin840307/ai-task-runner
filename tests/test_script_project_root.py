import json
from pathlib import Path

import pytest

from runner.config.runtime import RuntimeConfig
from runner.errors import RunnerError
from runner.runtime.run_state import RunState, StateStore
from runner.script_loader import load_yaml_script
from runner.script_runner import build_script_item_config, select_script_workflow


def base_args(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        project_root=str(tmp_path), work_dir='.ai-task-runner', resume=False,
        final_ai_validations=1, final_ai_required_passes=0,
        script='tasks.yaml', goal='', validator=None, validator_prompt='',
        ai_validator_prompt='', ai_validator_prompt_file=None,
    )


def test_yaml_item_project_root_is_optional_and_backward_compatible(tmp_path):
    script=tmp_path/'tasks.yaml'
    script.write_text('- prompt: old\n  validator: ai\n', encoding='utf-8')
    item=load_yaml_script(script)[0]
    child=build_script_item_config(base_args(tmp_path), item, 1)
    assert Path(child.project_root) == tmp_path.resolve()


def test_yaml_item_project_root_resolves_from_outer_project_root(tmp_path):
    project=tmp_path/'examples'/'one'; project.mkdir(parents=True)
    script=tmp_path/'tasks.yaml'
    script.write_text('- prompt: one\n  project_root: examples/one\n  validator: ai\n', encoding='utf-8')
    item=load_yaml_script(script)[0]
    child=build_script_item_config(base_args(tmp_path), item, 1)
    assert Path(child.project_root) == project.resolve()
    assert Path(child.project_root, child.work_dir, 'state.json') == (
        project / '.ai-task-runner' / 'script' / '001' / 'state.json'
    )


def test_yaml_item_inherits_cli_ui_auto_registration_flag(tmp_path):
    project = tmp_path / "one"
    project.mkdir()
    script = tmp_path / "tasks.yaml"
    script.write_text("- prompt: one\n  project_root: one\n  validator: ai\n", encoding="utf-8")
    item = load_yaml_script(script)[0]
    args = base_args(tmp_path)
    args.auto_register_ui_project = True

    child = build_script_item_config(args, item, 1)

    assert child.auto_register_ui_project is True


def test_yaml_item_project_root_rejects_empty_value(tmp_path):
    script=tmp_path/'tasks.yaml'
    script.write_text('- prompt: one\n  project_root: ""\n  validator: ai\n', encoding='utf-8')
    with pytest.raises(RunnerError, match='project_root must be a non-empty string'):
        load_yaml_script(script)

def test_execute_script_uses_distinct_item_project_roots(tmp_path):
    from runner.script_runner import execute_script
    (tmp_path/'a').mkdir(); (tmp_path/'b').mkdir()
    script=tmp_path/'tasks.yaml'
    script.write_text('''
- prompt: first
  project_root: a
  validator: ai
- prompt: second
  project_root: b
  validator: ai
''', encoding='utf-8')
    args=base_args(tmp_path); args.script=str(script); args.human_output=False; args.json_events=False; args.event_callback=None
    seen=[]
    def execute_one(child):
        seen.append((Path(child.project_root), Path(child.work_dir), child.script_index))
        root = Path(child.project_root)
        store = StateStore(root, root / child.work_dir)
        store.save(RunState(
            run_id=f"run-{child.script_index}", goal=child.goal,
            project_root=str(root), completed=True, stage="completed",
        ))
        return 0
    assert execute_script(args, execute_one)==0
    assert seen==[
        ((tmp_path/'a').resolve(), Path('.ai-task-runner')/'script'/'001', 1),
        ((tmp_path/'b').resolve(), Path('.ai-task-runner')/'script'/'002', 2),
    ]


def test_execute_script_does_not_treat_unfinished_child_as_pass(tmp_path):
    from runner.script_runner import execute_script

    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: first\n  validator: ai\n- prompt: second\n  validator: ai\n",
        encoding="utf-8",
    )
    args = base_args(tmp_path)
    args.script = str(script)
    args.human_output = False
    args.json_events = False
    args.event_callback = None
    seen = []

    def execute_one(child):
        seen.append(child.script_index)
        root = Path(child.project_root)
        StateStore(root, root / child.work_dir).save(RunState(
            run_id="unfinished", goal=child.goal, project_root=str(root),
            completed=False, stage="executing",
        ))
        return 0

    assert execute_script(args, execute_one) == 1
    assert seen == [1]


def test_yaml_item_goal_file_loads_relative_to_script(tmp_path):
    prompts=tmp_path/'prompts'; prompts.mkdir()
    goal=prompts/'goal.md'; goal.write_text('build from file\n', encoding='utf-8')
    script=tmp_path/'tasks.yaml'
    script.write_text('- goal_file: prompts/goal.md\n  validator: ai\n', encoding='utf-8')
    item=load_yaml_script(script)[0]
    assert item['goal'] == 'build from file'
    assert Path(item['goal_file']) == goal.resolve()
    child=build_script_item_config(base_args(tmp_path), item, 1)
    assert child.goal == 'build from file'
    assert Path(child.goal_file) == goal.resolve()


def test_yaml_item_goal_file_and_prompt_are_mutually_exclusive(tmp_path):
    goal=tmp_path/'goal.md'; goal.write_text('file goal', encoding='utf-8')
    script=tmp_path/'tasks.yaml'
    script.write_text('- prompt: inline\n  goal_file: goal.md\n  validator: ai\n', encoding='utf-8')
    with pytest.raises(RunnerError, match='either prompt or goal_file'):
        load_yaml_script(script)


def test_yaml_item_goal_file_missing_is_actionable(tmp_path):
    script=tmp_path/'tasks.yaml'
    script.write_text('- goal_file: missing.md\n  validator: ai\n', encoding='utf-8')
    with pytest.raises(RunnerError, match='goal_file not found: missing.md'):
        load_yaml_script(script)


def test_yaml_item_ai_validator_prompt_file_loads_relative_to_script(tmp_path):
    prompts = tmp_path / 'prompts'; prompts.mkdir()
    ai_prompt = prompts / 'validate.md'; ai_prompt.write_text('check genericity\n', encoding='utf-8')
    script = tmp_path / 'tasks.yaml'
    script.write_text('- prompt: build\n  validator: ai\n  ai_validator_prompt_file: prompts/validate.md\n', encoding='utf-8')
    item = load_yaml_script(script)[0]
    assert item['ai_validator_prompt'] == 'check genericity'
    assert Path(item['ai_validator_prompt_file']) == ai_prompt.resolve()
    child = build_script_item_config(base_args(tmp_path), item, 1)
    assert child.ai_validator_prompt == 'check genericity'
    assert Path(child.ai_validator_prompt_file) == ai_prompt.resolve()


def test_yaml_item_ai_validator_prompt_file_and_inline_are_mutually_exclusive(tmp_path):
    prompt = tmp_path / 'validate.md'; prompt.write_text('check', encoding='utf-8')
    script = tmp_path / 'tasks.yaml'
    script.write_text('- prompt: build\n  validator: ai\n  ai_validator_prompt: inline\n  ai_validator_prompt_file: validate.md\n', encoding='utf-8')
    with pytest.raises(RunnerError, match='either ai_validator_prompt or ai_validator_prompt_file'):
        load_yaml_script(script)


def test_yaml_item_ai_validator_prompt_file_missing_is_actionable(tmp_path):
    script = tmp_path / 'tasks.yaml'
    script.write_text('- prompt: build\n  validator: ai\n  ai_validator_prompt_file: missing.md\n', encoding='utf-8')
    with pytest.raises(RunnerError, match='ai_validator_prompt_file not found: missing.md'):
        load_yaml_script(script)


@pytest.mark.parametrize(
    ("field_name", "error_name"),
    [
        ("ai_validator_count", "final_ai_validations"),
        ("ai_validator_required_passes", "final_ai_required_passes"),
    ],
)
def test_yaml_item_numeric_counts_reject_booleans(tmp_path, field_name, error_name):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        f"- prompt: build\n  validator: ai\n  {field_name}: true\n",
        encoding="utf-8",
    )

    item = load_yaml_script(script)[0]
    with pytest.raises(RunnerError, match=error_name):
        build_script_item_config(base_args(tmp_path), item, 1)


def test_yaml_item_workflow_takes_precedence_over_cli_workflow(tmp_path):
    args = base_args(tmp_path)
    args.workflow = [{"name": "cli"}]
    args.workflow_explicit = True
    item = {"validator": "ai", "workflow": [{"name": "item"}]}

    workflow, explicit = select_script_workflow(args, item, "")

    assert workflow == [{"name": "item"}]
    assert explicit is True


def test_yaml_item_uses_cli_workflow_before_default(tmp_path):
    args = base_args(tmp_path)
    args.workflow = [{"name": "cli"}]
    args.workflow_explicit = True
    item = {"validator": "ai"}

    workflow, explicit = select_script_workflow(args, item, "")

    assert workflow == [{"name": "cli"}]
    assert explicit is True


def test_yaml_item_uses_default_workflow_when_no_explicit_workflow(tmp_path):
    workflow, explicit = select_script_workflow(
        base_args(tmp_path),
        {"validator": "validator.py"},
        "",
    )

    assert [stage["name"] for stage in workflow] == ["planning", "__plan_task__", "__plan_review__", "validate_file"]
    assert explicit is False


def test_yaml_item_validator_prompt_must_be_a_string(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: build\n  validator: ai\n  validator_prompt: [invalid]\n",
        encoding="utf-8",
    )

    with pytest.raises(RunnerError, match="validator_prompt must be a string"):
        load_yaml_script(script)


def test_yaml_item_task_runtime_options_match_cli_contract(tmp_path):
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
  api_wait_timeout: 71
  watchdog_interval: 2.5
  worker_hang_timeout: 601
  max_attempts: 4
  review_retries: 5
  max_cycles: 6
  retry_delay: 0.25
  retry_wait: 0.5
  retry_max_wait: 9
  ai_validator_count: 3
  ai_validator_required_passes: 2
  ai_validator_yolo: true
  readonly_safety: observe
""",
        encoding="utf-8",
    )

    item = load_yaml_script(script)[0]
    child = build_script_item_config(base_args(tmp_path), item, 1)

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
    assert child.api_retry_timeout == 71
    assert child.watchdog_interval == 2.5
    assert child.worker_hang_timeout == 601
    assert child.same_session_retries == 4
    assert child.review_retries == 5
    assert child.max_cycles == 6
    assert child.stage_retry_delay == 0.25
    assert child.api_retry_wait == 0.5
    assert child.api_retry_max_wait == 9
    assert child.final_ai_validations == 3
    assert child.final_ai_required_passes == 2
    assert child.ai_validator_yolo is True
    assert child.readonly_safety == "observe"


def test_yaml_item_ai_validator_yolo_rejects_non_boolean(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: build\n  validator: ai\n  ai_validator_yolo: yes please\n",
        encoding="utf-8",
    )
    item = load_yaml_script(script)[0]
    with pytest.raises(RunnerError, match="ai_validator_yolo must be a boolean"):
        build_script_item_config(base_args(tmp_path), item, 1)


def test_yaml_item_readonly_safety_rejects_invalid_value(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: build\n  validator: ai\n  readonly_safety: watch\n",
        encoding="utf-8",
    )
    item = load_yaml_script(script)[0]
    with pytest.raises(RunnerError, match="readonly_safety must be 'restore' or 'observe'"):
        build_script_item_config(base_args(tmp_path), item, 1)


def test_yaml_item_canonical_final_ai_names_are_supported(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: build\n  validator: ai\n  final_ai_validations: 5\n  final_ai_required_passes: 4\n",
        encoding="utf-8",
    )
    child = build_script_item_config(base_args(tmp_path), load_yaml_script(script)[0], 1)
    assert child.final_ai_validations == 5
    assert child.final_ai_required_passes == 4


def test_yaml_item_rejects_duplicate_final_ai_aliases(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: build\n  validator: ai\n  ai_validator_count: 3\n  final_ai_validations: 3\n",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="must not set both"):
        load_yaml_script(script)


def test_yaml_item_validator_args_use_runtime_list_validation(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: build\n  validator: ai\n  validator_args: --not-a-list\n",
        encoding="utf-8",
    )
    item = load_yaml_script(script)[0]
    with pytest.raises(RunnerError, match="validator_args must be a list"):
        build_script_item_config(base_args(tmp_path), item, 1)


def test_yaml_item_validator_args_reach_real_command_validator(tmp_path):
    from runner.api import RunRequest, run

    validator = tmp_path / "validation.py"
    validator.write_text(
        """from __future__ import annotations
import argparse
p = argparse.ArgumentParser()
p.add_argument('--project-root', required=True)
p.add_argument('--state-file', required=True)
p.add_argument('--case-token', required=True)
a = p.parse_args()
raise SystemExit(0 if a.case_token == 'YAML-OK' else 9)
""",
        encoding="utf-8",
    )
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """stages:
  validate_file:
    type: command
    result_kind: validation
    command: ["{python}", "{validator}", "--project-root", "{project_root}", "--state-file", "{state_file}", "{validator_args}"]
flow: [validate_file]
""",
        encoding="utf-8",
    )
    script = tmp_path / "tasks.yaml"
    script.write_text(
        f"- prompt: validate only\n"
        f"  validator: {validator.as_posix()}\n"
        f"  validator_args: [--case-token, YAML-OK]\n"
        f"  workflow_file: {workflow.as_posix()}\n",
        encoding="utf-8",
    )

    import sys
    fake_agent = Path(__file__).resolve().parent / "fake_agent.py"
    result = run(RunRequest(
        project_root=str(tmp_path),
        script=str(script),
        command=f'"{sys.executable}" "{fake_agent}"',
        retry_delay=0,
    ))

    assert result.completed is True
    assert result.exit_code == 0


def test_yaml_item_inline_workflow_is_normalized_from_script_directory(tmp_path):
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



def test_yaml_item_skip_on_max_cycles_must_be_boolean(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: build\n  validator: ai\n  skip_on_max_cycles: yes please\n",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="skip_on_max_cycles must be a boolean"):
        load_yaml_script(script)


def test_execute_script_can_skip_max_cycle_item_and_continue(tmp_path):
    from runner.errors import ConfigurationError
    from runner.script_runner import execute_script

    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: first\n  validator: ai\n  max_cycles: 2\n  skip_on_max_cycles: true\n"
        "- prompt: second\n  validator: ai\n",
        encoding="utf-8",
    )
    args = base_args(tmp_path)
    args.script = str(script)
    seen = []

    def execute_one(child):
        seen.append(child.script_index)
        root = Path(child.project_root)
        store = StateStore(root, root / child.work_dir)
        if child.script_index == 1:
            store.save(RunState(
                run_id="skip-me", goal=child.goal, project_root=str(root),
                cycle=2, completed=False, stage="validator_failed",
            ))
            raise ConfigurationError("max cycles reached: 2")
        store.save(RunState(
            run_id="done", goal=child.goal, project_root=str(root),
            completed=True, stage="completed",
        ))
        return 0

    assert execute_script(args, execute_one) == 0
    assert seen == [1, 2]
    marker = tmp_path / ".ai-task-runner" / "script" / "001" / "script-item-skipped.json"
    assert marker.is_file()
    assert "max cycles reached: 2" in marker.read_text(encoding="utf-8")


def test_execute_script_max_cycles_still_fails_without_skip_flag(tmp_path):
    from runner.errors import ConfigurationError
    from runner.script_runner import execute_script

    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: first\n  validator: ai\n  max_cycles: 2\n",
        encoding="utf-8",
    )
    args = base_args(tmp_path)
    args.script = str(script)

    def execute_one(child):
        raise ConfigurationError("max cycles reached: 2")

    with pytest.raises(ConfigurationError, match="max cycles reached: 2"):
        execute_script(args, execute_one)


def test_execute_script_resume_honors_durable_max_cycle_skip_marker(tmp_path):
    from runner.script_loader import load_yaml_script
    from runner.script_runner import _script_item_fingerprint, execute_script

    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: first\n  validator: ai\n  skip_on_max_cycles: true\n"
        "- prompt: second\n  validator: ai\n",
        encoding="utf-8",
    )
    marker = tmp_path / ".ai-task-runner" / "script" / "001" / "script-item-skipped.json"
    marker.parent.mkdir(parents=True)
    item = load_yaml_script(script, allow_missing_files=True)[0]
    marker.write_text(json.dumps({
        "reason": "max cycles reached: 2",
        "item_fingerprint": _script_item_fingerprint(item),
    }), encoding="utf-8")
    args = base_args(tmp_path)
    args.script = str(script)
    args.resume = True
    seen = []

    def execute_one(child):
        seen.append(child.script_index)
        root = Path(child.project_root)
        StateStore(root, root / child.work_dir).save(RunState(
            run_id="done", goal=child.goal, project_root=str(root),
            completed=True, stage="completed",
        ))
        return 0

    assert execute_script(args, execute_one) == 0
    assert seen == [2]


def test_execute_script_resume_ignores_skip_marker_for_changed_item(tmp_path):
    from runner.script_loader import load_yaml_script
    from runner.script_runner import _script_item_fingerprint, execute_script

    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: original\n  validator: ai\n  skip_on_max_cycles: true\n",
        encoding="utf-8",
    )
    old_item = load_yaml_script(script, allow_missing_files=True)[0]
    marker = tmp_path / ".ai-task-runner" / "script" / "001" / "script-item-skipped.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({
        "reason": "max cycles reached: 2",
        "item_fingerprint": _script_item_fingerprint(old_item),
    }), encoding="utf-8")

    script.write_text(
        "- prompt: changed\n  validator: ai\n  skip_on_max_cycles: true\n",
        encoding="utf-8",
    )
    args = base_args(tmp_path)
    args.script = str(script)
    args.resume = True
    seen = []

    def execute_one(child):
        seen.append(child.goal)
        root = Path(child.project_root)
        StateStore(root, root / child.work_dir).save(RunState(
            run_id="done", goal=child.goal, project_root=str(root),
            completed=True, stage="completed",
        ))
        return 0

    assert execute_script(args, execute_one) == 0
    assert seen == ["changed"]
    assert not marker.exists()
