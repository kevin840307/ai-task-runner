import argparse
from pathlib import Path

import pytest

from runner.errors import RunnerError
from runner.script_runner import load_yaml_script, script_item_args


def base_args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=str(tmp_path), work_dir='.ai-task-runner', resume=False,
        final_ai_validations=1, final_ai_required_passes=0,
        script='tasks.yaml', goal=None, validator=None, validator_prompt='',
        ai_validator_prompt='',
    )


def test_yaml_item_project_root_is_optional_and_backward_compatible(tmp_path):
    script=tmp_path/'tasks.yaml'
    script.write_text('- prompt: old\n  validator: ai\n', encoding='utf-8')
    item=load_yaml_script(script)[0]
    child=script_item_args(base_args(tmp_path), item, 1)
    assert Path(child.project_root) == tmp_path.resolve()


def test_yaml_item_project_root_resolves_from_outer_project_root(tmp_path):
    project=tmp_path/'examples'/'one'; project.mkdir(parents=True)
    script=tmp_path/'tasks.yaml'
    script.write_text('- prompt: one\n  project_root: examples/one\n  validator: ai\n', encoding='utf-8')
    item=load_yaml_script(script)[0]
    child=script_item_args(base_args(tmp_path), item, 1)
    assert Path(child.project_root) == project.resolve()
    assert Path(child.project_root, child.work_dir, 'state.json') == project/'.ai-task-runner/script/001/state.json'


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
        seen.append((Path(child.project_root), child.work_dir, child.script_index))
        return 0
    assert execute_script(args, execute_one)==0
    assert seen==[
        ((tmp_path/'a').resolve(), '.ai-task-runner/script/001', 1),
        ((tmp_path/'b').resolve(), '.ai-task-runner/script/002', 2),
    ]


def test_yaml_item_goal_file_loads_relative_to_script(tmp_path):
    prompts=tmp_path/'prompts'; prompts.mkdir()
    goal=prompts/'goal.md'; goal.write_text('build from file\n', encoding='utf-8')
    script=tmp_path/'tasks.yaml'
    script.write_text('- goal_file: prompts/goal.md\n  validator: ai\n', encoding='utf-8')
    item=load_yaml_script(script)[0]
    assert item['prompt'] == 'build from file'
    assert Path(item['goal_file']) == goal.resolve()
    child=script_item_args(base_args(tmp_path), item, 1)
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
