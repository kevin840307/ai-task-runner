import json, os, subprocess, sys, tempfile, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def run_flow(tmp_path, backend):
    validator=tmp_path/'validator.py'
    validator.write_text('import argparse\np=argparse.ArgumentParser();p.add_argument("--project-root");p.add_argument("--state-file");p.parse_args();raise SystemExit(0)\n')
    before=validator.read_bytes()
    cmd=f'"{sys.executable}" "{ROOT/"tests/fake_agent.py"}"'
    args=[sys.executable,str(ROOT/'ai_task_runner.py'),'--backend',backend,'--goal','x','--project-root',str(tmp_path),'--validator',str(validator),'--command',cmd,'--retry-delay','0']
    r=subprocess.run(args,capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
    assert validator.read_bytes()==before
    state=json.loads((tmp_path/'.ai-task-runner/state.json').read_text())
    assert state['completed'] is True
    assert state['agent_session_id'] == 'test-session-001'
    assert 'AI 正在理解並拆分任務' in r.stdout
    assert '正在執行最終驗證' in r.stdout

def test_qwen_same_session(tmp_path):
    run_flow(tmp_path,'qwen')

def test_opencode_same_session(tmp_path):
    run_flow(tmp_path,'opencode')


def test_qwen_ai_validator_uses_fresh_session(tmp_path):
    cmd=f'"{sys.executable}" "{ROOT/"tests/fake_agent.py"}"'
    args=[sys.executable,str(ROOT/'ai_task_runner.py'),'--backend','qwen','--goal','x',
          '--project-root',str(tmp_path),'--validator','ai','--command',cmd,'--retry-delay','0']
    r=subprocess.run(args,capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
    state=json.loads((tmp_path/'.ai-task-runner/state.json').read_text())
    assert state['completed'] is True
    assert state['agent_session_id'] == 'test-session-001'
    assert 'AI · new session' in r.stdout

def test_opencode_ai_validator_uses_fresh_session(tmp_path):
    cmd=f'"{sys.executable}" "{ROOT/"tests/fake_agent.py"}"'
    args=[sys.executable,str(ROOT/'ai_task_runner.py'),'--backend','opencode','--goal','x',
          '--project-root',str(tmp_path),'--validator','ai','--command',cmd,'--retry-delay','0']
    r=subprocess.run(args,capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
    state=json.loads((tmp_path/'.ai-task-runner/state.json').read_text())
    assert state['completed'] is True
    assert state['agent_session_id'] == 'test-session-001'

def test_yaml_script_runs_items_in_order(tmp_path):
    script = tmp_path/'tasks.yaml'
    script.write_text('''
- prompt: first task
  validator: ai
- prompt: second task
  validator: ai
  validator_prompt: verify carefully
''', encoding='utf-8')
    cmd=f'"{sys.executable}" "{ROOT/"tests/fake_agent.py"}"'
    args=[sys.executable,str(ROOT/'ai_task_runner.py'),'--backend','qwen',
          '--project-root',str(tmp_path),'--script',str(script),'--command',cmd,'--retry-delay','0']
    r=subprocess.run(args,capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
    assert '[Script 1/2] PASS' in r.stdout
    assert '[Script 2/2] PASS' in r.stdout
    for i in (1,2):
        state=json.loads((tmp_path/f'.ai-task-runner/script/{i:03d}/state.json').read_text())
        assert state['completed'] is True
        assert state['agent_session_id']=='test-session-001'


def test_yaml_script_rejects_missing_validator(tmp_path):
    script=tmp_path/'bad.yaml'
    script.write_text('- prompt: missing validator\n',encoding='utf-8')
    r=subprocess.run([sys.executable,str(ROOT/'ai_task_runner.py'),'--project-root',str(tmp_path),'--script',str(script)],capture_output=True,text=True)
    assert r.returncode==1
    assert 'requires validator' in r.stderr

def test_all_model_phases_retry_and_finish(tmp_path):
    cmd=f'"{sys.executable}" "{ROOT/"tests/flaky_agent.py"}"'
    state_dir = Path(tempfile.mkdtemp(prefix=f"{tmp_path.name}-flaky-", dir=tmp_path.parent))
    env = {**os.environ, "FLAKY_STATE_DIR": str(state_dir)}
    args=[sys.executable,str(ROOT/'ai_task_runner.py'),'--backend','qwen','--goal','x',
          '--project-root',str(tmp_path),'--validator','ai','--command',cmd,
          '--retry-delay','0','--retry-wait','0','--retry-max-wait','0']
    r=subprocess.run(args,capture_output=True,text=True,env=env)
    assert r.returncode==0,r.stdout+r.stderr
    for phase in ('plan','execute','review','validator'):
        assert (state_dir/f'.{phase}.count').read_text() == '2'
    state=json.loads((tmp_path/'.ai-task-runner/state.json').read_text())
    assert state['completed'] is True
    assert state['agent_session_id']=='retry-session-001'


def test_model_calls_have_configurable_python_timeout():
    cli = (ROOT / "ai_task_runner.py").read_text(encoding="utf-8")
    api = (ROOT / "runner_api.py").read_text(encoding="utf-8")
    backend = (ROOT / "backends/base.py").read_text(encoding="utf-8")
    process_control = (ROOT / "process_control.py").read_text(encoding="utf-8")

    assert '"--agent-timeout"' in cli
    assert "agent_timeout: int = 7200" in api
    assert "run_process(command, self.root, self.timeout)" in backend
    assert "timeout=timeout or None" in process_control
    assert "terminate_process_tree" in process_control



def test_task_schema_is_strict():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner", ROOT / "ai_task_runner.py")
    runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner
    spec.loader.exec_module(runner)

    valid = '{"tasks":[{"title":"A","description":"B","acceptance_criteria":["C"]}]}'
    assert runner.parse_tasks(valid, 1)[0].title == "A"

    invalid_values = [
        '{"tasks":[{"title":1,"description":"B","acceptance_criteria":["C"]}]}',
        '{"tasks":[{"title":"A","description":"B","acceptance_criteria":"C"}]}',
        '{"tasks":[{"title":"A","description":"B","acceptance_criteria":[]}]}',
    ]
    for value in invalid_values:
        try:
            runner.parse_tasks(value, 1)
        except runner.RunnerError:
            pass
        else:
            raise AssertionError(f"schema accepted invalid value: {value}")


def test_task_schema_accepts_common_criteria_alias():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner", ROOT / "ai_task_runner.py")
    runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner
    spec.loader.exec_module(runner)

    value = '{"tasks":[{"title":"A","description":"B","accept_criteria":["C"]}]}'
    task = runner.parse_tasks(value, 1)[0]
    assert task.acceptance_criteria == ["C"]


def test_prompts_forbid_questions_and_omit_runtime_fields():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner_prompts", ROOT / "ai_task_runner.py")
    runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner
    spec.loader.exec_module(runner)

    root = Path("/project")
    task = runner.Task("id", "Title", "Description", ["Done"], attempts=9, last_output="large output")
    state = runner.State("run", "goal", str(root), tasks=[task])
    protected = [root / "state.json"]
    prompts = [
        runner.plan_prompt("goal", root, state, protected),
        runner.execution_prompt(state, root, protected),
        runner.review_prompt(state, root, protected, "report"),
        runner.ai_validator_prompt("goal", root, protected),
    ]
    assert all("ask questions" in prompt.lower() for prompt in prompts)
    assert '"attempts"' not in prompts[1]
    assert '"last_output"' not in prompts[1]
    assert '"status"' not in prompts[1]
    assert all('do not invent' in prompt.lower() for prompt in prompts)
    assert '"missing_items":[]' in prompts[2]
    assert '"missing_items":[]' in prompts[3]



def test_yaml_resume_reuses_existing_item_states(tmp_path):
    script = tmp_path / "tasks.yaml"
    script.write_text("""
- prompt: first task
  validator: ai
- prompt: second task
  validator: ai
""", encoding="utf-8")
    cmd = f'"{sys.executable}" "{ROOT / "tests/fake_agent.py"}"'
    args = [sys.executable, str(ROOT / "ai_task_runner.py"), "--backend", "qwen",
            "--project-root", str(tmp_path), "--script", str(script), "--command", cmd,
            "--retry-delay", "0"]
    first = subprocess.run(args, capture_output=True, text=True)
    assert first.returncode == 0, first.stdout + first.stderr
    state_paths = [tmp_path / f".ai-task-runner/script/{i:03d}/state.json" for i in (1, 2)]
    run_ids = [json.loads(path.read_text())["run_id"] for path in state_paths]

    resumed = subprocess.run([*args, "--resume"], capture_output=True, text=True)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert [json.loads(path.read_text())["run_id"] for path in state_paths] == run_ids


def _scenario_env(tmp_path, scenario):
    state_dir = Path(tempfile.mkdtemp(prefix=f"{tmp_path.name}-{scenario}-", dir=tmp_path.parent))
    return {**os.environ, "SCENARIO": scenario, "SCENARIO_STATE_DIR": str(state_dir)}, state_dir


def _scenario_args(tmp_path, scenario, validator="ai", extra=None):
    cmd = f'"{sys.executable}" "{ROOT / "tests/scenario_agent.py"}"'
    args = [sys.executable, str(ROOT / "ai_task_runner.py"), "--backend", "qwen",
            "--goal", "x", "--project-root", str(tmp_path), "--validator", str(validator),
            "--command", cmd, "--retry-delay", "0", "--retry-wait", "0", "--retry-max-wait", "0"]
    return [*args, *(extra or [])]


def test_review_and_ai_validator_restore_project_changes(tmp_path):
    env, state_dir = _scenario_env(tmp_path, "readonly")
    result = subprocess.run(_scenario_args(tmp_path, "readonly"), capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "review_mutation.txt").exists()
    assert not (tmp_path / "validator_mutation.txt").exists()
    assert (state_dir / "review.count").read_text() == "2"
    assert (state_dir / "validator.count").read_text() == "2"


def test_review_incomplete_reexecutes_current_task(tmp_path):
    env, state_dir = _scenario_env(tmp_path, "review_retry")
    result = subprocess.run(_scenario_args(tmp_path, "review_retry"), capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (state_dir / "execute.count").read_text() == "2"
    assert (state_dir / "review.count").read_text() == "2"
    state = json.loads((tmp_path / ".ai-task-runner/state.json").read_text())
    assert state["tasks"][0]["attempts"] == 2


def test_protected_file_change_is_restored_and_retried(tmp_path):
    protected = tmp_path / "protected.txt"
    protected.write_text("original", encoding="utf-8")
    env, state_dir = _scenario_env(tmp_path, "protected_retry")
    env["PROTECTED_PATH"] = str(protected)
    result = subprocess.run(
        _scenario_args(tmp_path, "protected_retry", extra=["--protect-file", str(protected)]),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert protected.read_text(encoding="utf-8") == "original"
    assert (state_dir / "execute.count").read_text() == "2"


def test_file_validator_failure_replans_and_then_passes(tmp_path):
    validator = tmp_path / "validator.py"
    validator.write_text(
        """import argparse
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--project-root'); p.add_argument('--state-file'); a=p.parse_args()
path=Path(a.project_root)/'.validator.count'
count=int(path.read_text()) if path.exists() else 0
path.write_text(str(count+1))
raise SystemExit(0 if count >= 1 else 1)
""",
        encoding="utf-8",
    )
    cmd = f'"{sys.executable}" "{ROOT / "tests/fake_agent.py"}"'
    args = [sys.executable, str(ROOT / "ai_task_runner.py"), "--backend", "qwen", "--goal", "x",
            "--project-root", str(tmp_path), "--validator", str(validator), "--command", cmd,
            "--retry-delay", "0", "--retry-wait", "0", "--retry-max-wait", "0"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((tmp_path / ".ai-task-runner/state.json").read_text())
    assert state["cycle"] == 2
    assert len(state["tasks"]) == 2
    assert all(task["status"] == "completed" for task in state["tasks"])
    assert (tmp_path / ".validator.count").read_text() == "2"



def test_ai_validator_failure_replans_and_then_passes(tmp_path):
    env, state_dir = _scenario_env(tmp_path, "ai_replan")
    result = subprocess.run(_scenario_args(tmp_path, "ai_replan"), capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((tmp_path / ".ai-task-runner/state.json").read_text())
    assert state["cycle"] == 2
    assert len(state["tasks"]) == 2
    assert all(task["status"] == "completed" for task in state["tasks"])
    assert (state_dir / "validator.count").read_text() == "2"


def test_no_progress_adds_different_strategy_instruction(tmp_path):
    env, state_dir = _scenario_env(tmp_path, "stagnation")
    result = subprocess.run(
        _scenario_args(tmp_path, "stagnation"),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (state_dir / "execute.count").read_text() == "4"
    assert (state_dir / "strategy_seen.txt").read_text() == "yes"


def test_expired_session_is_replaced_and_work_continues(tmp_path):
    state_dir = Path(tempfile.mkdtemp(prefix=f"{tmp_path.name}-session-", dir=tmp_path.parent))
    env = {**os.environ, "SESSION_TEST_STATE_DIR": str(state_dir)}
    command = f'"{sys.executable}" "{ROOT / "tests/session_expired_agent.py"}"'
    args = [
        sys.executable,
        str(ROOT / "ai_task_runner.py"),
        "--backend",
        "qwen",
        "--goal",
        "x",
        "--project-root",
        str(tmp_path),
        "--validator",
        "ai",
        "--command",
        command,
        "--retry-delay",
        "0",
        "--retry-wait",
        "0",
        "--retry-max-wait",
        "0",
    ]
    result = subprocess.run(args, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((tmp_path / ".ai-task-runner/state.json").read_text())
    assert state["agent_session_id"] == "new-session"
    assert (state_dir / "execute.count").read_text() == "2"


def test_readonly_guard_ignores_build_and_dependency_directories(tmp_path):
    from runner_support import readonly_project_call

    work = tmp_path / ".ai-task-runner"
    source = tmp_path / "source.txt"
    dependency = tmp_path / "node_modules" / "cache.txt"
    nested_build = tmp_path / "app" / "target" / "cache.txt"
    source.write_text("original", encoding="utf-8")
    dependency.parent.mkdir(parents=True)
    dependency.write_text("old", encoding="utf-8")
    nested_build.parent.mkdir(parents=True)
    nested_build.write_text("old", encoding="utf-8")

    def mutate() -> str:
        source.write_text("changed", encoding="utf-8")
        dependency.write_text("new", encoding="utf-8")
        nested_build.write_text("new", encoding="utf-8")
        return "ok"

    result, changed = readonly_project_call(mutate, tmp_path, work)
    assert result == "ok"
    assert source.read_text(encoding="utf-8") == "original"
    assert dependency.read_text(encoding="utf-8") == "new"
    assert nested_build.read_text(encoding="utf-8") == "new"
    assert changed == ["source.txt"]


def test_cleanup_removes_interrupted_writes_and_old_readonly_backups(tmp_path):
    from runner_support import cleanup_stale_artifacts

    work = tmp_path / "work"
    work.mkdir()
    interrupted = work / "state.json.tmp"
    interrupted.write_text("partial", encoding="utf-8")

    temp_root = tmp_path / "temp"
    stale = temp_root / "ai-task-runner-readonly-stale"
    recent = temp_root / "ai-task-runner-readonly-recent"
    stale.mkdir(parents=True)
    recent.mkdir()
    old = time.time() - 100
    os.utime(stale, (old, old))

    cleanup_stale_artifacts(work, temp_root=temp_root, older_than=10)

    assert not interrupted.exists()
    assert not stale.exists()
    assert recent.exists()


def test_review_and_validator_results_are_bounded():
    from runner_support import (
        MAX_MISSING_ITEM_CHARS,
        MAX_MISSING_ITEMS,
        MAX_RESULT_REASON_CHARS,
        parse_ai_validation,
        parse_review,
    )

    missing = ["x" * (MAX_MISSING_ITEM_CHARS + 10)] * (MAX_MISSING_ITEMS + 5)
    review = parse_review(json.dumps({
        "completed": False,
        "reason": "r" * (MAX_RESULT_REASON_CHARS + 10),
        "missing_items": missing,
    }))
    validation = parse_ai_validation(json.dumps({
        "passed": False,
        "reason": "r" * (MAX_RESULT_REASON_CHARS + 10),
        "missing_items": missing,
    }))

    for result in (review, validation):
        assert len(result["reason"]) == MAX_RESULT_REASON_CHARS
        assert len(result["missing_items"]) == MAX_MISSING_ITEMS
        assert all(
            len(item) == MAX_MISSING_ITEM_CHARS
            for item in result["missing_items"]
        )


def test_old_state_without_24h_fields_still_loads():
    from models import State

    state = State.load({
        "run_id": "run",
        "goal": "goal",
        "project_root": "/project",
        "tasks": [{
            "id": "c01-t001",
            "title": "Task",
            "description": "Description",
            "acceptance_criteria": ["Done"],
        }],
    })

    assert state.tasks[0].progress_key == ""
    assert state.tasks[0].stagnant_attempts == 0


def test_prompts_require_project_understanding_and_minimal_compatible_changes(tmp_path):
    import runner_support
    from models import State, Task

    state = State(
        run_id="test-run",
        goal="add feature",
        project_root=str(tmp_path),
        tasks=[Task("t1", "Implement", "Add the feature", ["Existing behavior still works"])],
    )
    protected = [tmp_path / ".ai-task-runner" / "state.json"]

    plan = runner_support.plan_prompt(state.goal, tmp_path, state, protected)
    execute = runner_support.execution_prompt(state, tmp_path, protected)
    review = runner_support.review_prompt(state, tmp_path, protected, "done")

    for prompt in (plan, execute, review):
        assert "relevant project structure" in prompt
        assert "smallest maintainable change" in prompt
        assert "Preserve existing behavior, public interfaces, file formats, and dependencies" in prompt
        assert "Avoid unrelated refactoring, duplication, speculative features, and unnecessary dependencies" in prompt

    assert "entry points, dependencies, public interfaces, conventions, and existing tests" in plan
    assert "verify the change is scoped, maintainable, and preserves relevant existing behavior" in review


def test_plan_prompt_includes_project_outline_and_forbids_tools(tmp_path):
    import runner_support
    from models import State

    (tmp_path / "README.md").write_text("fixture", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')", encoding="utf-8")
    state = State("run", "goal", str(tmp_path))

    prompt = runner_support.plan_prompt(
        state.goal,
        tmp_path,
        state,
        [tmp_path / ".ai-task-runner" / "state.json"],
    )

    assert "Project files:" in prompt
    assert "README.md" in prompt
    assert "src/app.py" in prompt
    assert "If planning notes are written" in prompt
    assert "Do not create, edit, delete, or rename project implementation files during planning" in prompt
    assert ".ai-task-runner/state.json" not in prompt


def test_qwen_planning_args_preserve_yolo():
    import runner_core

    args = [
        "--approval-mode",
        "yolo",
        "--model",
        "Qwen3.5-4B",
        "--max-tool-calls",
        "20",
    ]

    assert runner_core.planning_agent_args("qwen", args) == [
        *args,
        "--safe-mode",
        "--exclude-tools",
        "read_file",
        "--exclude-tools",
        "read_mcp_resource",
        "--exclude-tools",
        "list_directory",
        "--exclude-tools",
        "glob",
        "--exclude-tools",
        "grep_search",
        "--exclude-tools",
        "write_file",
        "--exclude-tools",
        "edit",
        "--exclude-tools",
        "notebook_edit",
        "--exclude-tools",
        "run_shell_command",
        "--exclude-tools",
        "tool_search",
        "--exclude-tools",
        "todo_write",
    ]
    assert runner_core.planning_agent_args("opencode", args) == args
