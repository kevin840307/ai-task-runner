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


def test_plan_only_stops_after_todo_creation(tmp_path):
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import argparse\n"
        "p=argparse.ArgumentParser();p.add_argument('--project-root');"
        "p.add_argument('--state-file');p.parse_args();raise SystemExit(0)\n",
        encoding="utf-8",
    )
    cmd = f'"{sys.executable}" "{ROOT/"tests/fake_agent.py"}"'
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
        str(validator),
        "--command",
        cmd,
        "--plan-only",
        "--retry-delay",
        "0",
        "--retry-wait",
        "0",
    ]
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((tmp_path / ".ai-task-runner/state.json").read_text())
    assert state["tasks"][0]["title"] == "Create marker"
    assert state["completed"] is False
    assert not (tmp_path / "done.txt").exists()


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
    assert "DEFAULT_AGENT_TIMEOUT" in api
    assert '"--planning-timeout"' in cli
    assert "DEFAULT_PLANNING_TIMEOUT" in api
    assert '"--agent-idle-after-change-timeout"' in cli
    assert "DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT" in api
    assert "idle_timeout_after_change" in backend
    assert "timeout=timeout or None" in process_control
    assert "idle_timed_out" in process_control
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


def test_goal_task_derivation_splits_numbered_deliverables():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner_core", ROOT / "runner_core.py")
    runner_core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner_core
    spec.loader.exec_module(runner_core)

    tasks = runner_core.derive_tasks_from_goal(
        "Build release packet.\n1. Create VERSION.\n2. Create CHANGELOG.md.\n3. Create summary JSON.",
        2,
    )
    assert [task.id for task in tasks] == ["c02-t001", "c02-t002", "c02-t003"]
    assert [task.title for task in tasks] == [
        "Create VERSION",
        "Create CHANGELOG.md",
        "Create summary JSON",
    ]

    assert len(runner_core.derive_tasks_from_goal("Build one thing", 1)) == 1


def test_goal_task_derivation_uses_single_repair_task_after_validator_failure():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner_core", ROOT / "runner_core.py")
    runner_core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner_core
    spec.loader.exec_module(runner_core)

    tasks = runner_core.derive_tasks_from_goal(
        "Create a document.\n1. ## Overview\n2. ## Complexity Table\n3. ## Worked Example",
        5,
        "score=75/100\nmissing exact complexity table header",
    )

    assert len(tasks) == 1
    assert tasks[0].id == "c05-t001"
    assert tasks[0].title == "Repair validator failure"
    assert "missing exact complexity table header" in tasks[0].description
    assert "current rejected behavior or output" in tasks[0].description

    tasks = runner_core.derive_tasks_from_goal(
        "Build a CLI",
        6,
        "unexpected stored JSON:\n{\"todos\": []}",
    )
    assert "the actual bad value to change away from" in tasks[0].description


def test_goal_task_derivation_splits_structured_validator_errors():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner_core", ROOT / "runner_core.py")
    runner_core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner_core
    spec.loader.exec_module(runner_core)

    tasks = runner_core.derive_tasks_from_goal(
        "Generate config outputs",
        7,
        (
            "VALIDATION_FAILED\n"
            "errors: 2\n"
            "[E005] check_config_shape failed\n"
            "- shared values are repeated\n"
            "Full report: .ai-task-runner/validator-reports/x/shape.txt\n"
            "[E007] check_rendered_output failed\n"
            "- missing output files\n"
            "Full report: .ai-task-runner/validator-reports/x/output.txt\n"
        ),
    )

    assert [task.id for task in tasks] == ["c07-t001", "c07-t002"]
    assert tasks[0].title == "Repair E005: check_config_shape failed"
    assert tasks[1].title == "Repair E007: check_rendered_output failed"
    assert "shared values are repeated" in tasks[0].description
    assert "missing output files" not in tasks[0].description
    assert "missing output files" in tasks[1].description


def test_repair_review_requires_project_change_when_validator_failed():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner_core", ROOT / "runner_core.py")
    runner_core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner_core
    spec.loader.exec_module(runner_core)

    state = runner_core.RunState("run", "goal", "/project")
    state.validator_output = "score=79/100"
    task = runner_core.Task("id", "Repair validator failure", "fix", [])
    review = {"completed": True, "reason": "ok", "missing_items": []}

    assert runner_core.repair_review_needs_project_change(state, task, review, False)
    assert not runner_core.repair_review_needs_project_change(state, task, review, True)
    defer_review = {
        "completed": True,
        "defer_to_validator": True,
        "reason": "use validator",
        "missing_items": [],
    }
    assert not runner_core.repair_review_needs_project_change(
        state,
        task,
        defer_review,
        False,
    )
    assert runner_core.validator_repair_should_use_file_validator(state, task, True)
    assert not runner_core.validator_repair_should_use_file_validator(state, task, False)
    assert not runner_core.validator_repair_should_use_file_validator(
        state,
        runner_core.Task("id", "Normal task", "fix", []),
        True,
    )
    split_task = runner_core.Task(
        "id",
        "Repair E003: check_renderer_source failed",
        "fix",
        [],
    )
    assert runner_core.is_validator_repair_task(split_task)
    assert runner_core.repair_review_needs_project_change(
        state,
        split_task,
        review,
        False,
    )
    assert runner_core.validator_repair_should_use_file_validator(
        state,
        split_task,
        True,
    )


def test_goal_task_derivation_splits_natural_deliverable_paragraphs():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner_core", ROOT / "runner_core.py")
    runner_core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner_core
    spec.loader.exec_module(runner_core)

    tasks = runner_core.derive_tasks_from_goal(
        (
            "Build a small CSV sales analyzer from input/sales.csv.\n\n"
            "The finished tool should include analyze_sales.py and a CLI.\n\n"
            "It should produce report.json with totals.\n\n"
            "README.md should document Usage and Outputs.\n\n"
            "Do not ask questions."
        ),
        3,
    )
    assert len(tasks) == 3
    assert tasks[0].id == "c03-t001"
    assert tasks[-1].title == "README.md should document Usage and Outputs"
    assert not any(task.title.startswith("Build a small CSV") for task in tasks)
    assert not any("Do not ask" in task.title for task in tasks)


def test_planned_tasks_are_right_sized_when_planner_under_splits_goal():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner_core", ROOT / "runner_core.py")
    runner_core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner_core
    spec.loader.exec_module(runner_core)

    planned = [
        runner_core.Task(
            "c01-t001",
            "Build everything",
            "Implement the whole request.",
            ["Done"],
        )
    ]
    goal = (
        "Build a safe arithmetic expression evaluator.\n\n"
        "The finished tool should include expression_eval.py with evaluate().\n\n"
        "The CLI should support single expression and batch commands.\n\n"
        "Batch mode should generate results.json and results.md. README.md should document Usage."
    )

    tasks = runner_core.right_size_planned_tasks(goal, 1, planned)

    assert len(tasks) == 3
    assert tasks[0].title.startswith("The finished tool should include")
    assert runner_core.right_size_planned_tasks(goal, 2, planned, "validator fail") is planned


def test_goal_task_derivation_splits_dense_complex_prompt():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner_core", ROOT / "runner_core.py")
    runner_core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner_core
    spec.loader.exec_module(runner_core)

    goal = (
        "Build a small inventory CLI with inventory.py and commands to add, list, "
        "and remove items. Store data in inventory.json with sku, name, quantity, "
        "and price fields. Generate report.json and report.md summaries. Also "
        "write README.md usage docs and include focused tests."
    )

    tasks = runner_core.derive_tasks_from_goal(goal, 1)

    assert len(tasks) >= 4
    assert any("inventory.py" in task.title for task in tasks)
    assert any("inventory.json" in task.title for task in tasks)
    assert any("report.json" in task.title for task in tasks)
    assert any("README.md" in task.title for task in tasks)


def test_goal_task_derivation_uses_markdown_sections_for_specs():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner_core", ROOT / "runner_core.py")
    runner_core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner_core
    spec.loader.exec_module(runner_core)

    goal = (ROOT / "examples" / "07_auto_config" / "prompt.md").read_text(
        encoding="utf-8"
    )
    tasks = runner_core.derive_tasks_from_goal(goal, 1)
    titles = [task.title for task in tasks]

    assert 10 <= len(tasks) <= 20
    assert any("Required CLI" in title for title in titles)
    assert any("load YAML config" in title for title in titles)
    assert any("deep merge config values" in title for title in titles)
    assert any("render Jinja2 templates" in title for title in titles)
    assert any("shared apps, versions, profiles" in title for title in titles)
    assert any(title == "Merge Order" for title in titles)
    assert any(title == "Templates" for title in titles)
    assert any(title == "Expected Result" for title in titles)
    assert not any(title.startswith("workflow:") for title in titles)
    assert not any(title.startswith("`config/") for title in titles)


def test_goal_task_derivation_keeps_persistence_deliverables():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner_core", ROOT / "runner_core.py")
    runner_core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner_core
    spec.loader.exec_module(runner_core)

    tasks = runner_core.derive_tasks_from_goal(
        (
            "Build a small persistent todo CLI.\n\n"
            "The finished tool should include todo_cli.py and support add/list/done.\n\n"
            "Todos should be stored in a JSON file selected by --db. "
            "Each todo should have id, text, priority, and done fields.\n\n"
            "Export should write a Markdown summary file. README.md should document usage."
        ),
        4,
    )
    assert len(tasks) == 3
    assert any("stored in a JSON file" in task.title for task in tasks)


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
    prompt_with_legacy_hint = runner.execution_prompt(
        state,
        root,
        protected,
        validator_hint='["python","validator.py"]',
    )
    assert "Validator reference" in prompt_with_legacy_hint
    assert "validator.py" in prompt_with_legacy_hint
    assert "You may read validator files" in prompt_with_legacy_hint
    assert "never modify them or hardcode validator internals" in prompt_with_legacy_hint
    assert "Do not delegate to subagents" in prompt_with_legacy_hint
    assert "Do not use computer-use" in prompt_with_legacy_hint
    assert "instead of repeating the same read/check command" in prompt_with_legacy_hint
    assert "treat it as authoritative" in prompt_with_legacy_hint

    state.validator_output = "unexpected file content"
    review_with_feedback = runner.review_prompt(state, root, protected, "report")
    assert "Latest validator feedback to consider" in review_with_feedback
    assert "Do not mark the task complete unless the reported failure is fixed" in review_with_feedback



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


def test_planned_task_list_runs_each_task_then_review_in_order(tmp_path):
    validator = tmp_path / "validator.py"
    env, state_dir = _scenario_env(tmp_path, "multi_task_plan")
    validator.write_text(
        f"""import argparse
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--project-root'); p.add_argument('--state-file'); a=p.parse_args()
root=Path(a.project_root)
expected=['execute:first','review:first','execute:second','review:second']
actual=Path({str(state_dir / "order.log")!r}).read_text(encoding='utf-8').splitlines()
if actual != expected:
    print(actual)
    raise SystemExit(1)
if not (root/'first.txt').exists() or not (root/'second.txt').exists():
    print('missing marker')
    raise SystemExit(1)
print('PASS')
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        _scenario_args(tmp_path, "multi_task_plan", validator=validator),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((tmp_path / ".ai-task-runner/state.json").read_text())
    assert [task["title"] for task in state["tasks"]] == [
        "Create first marker",
        "Create second marker",
    ]
    assert [task["status"] for task in state["tasks"]] == [
        "completed",
        "completed",
    ]
    assert all(task["last_review"]["completed"] for task in state["tasks"])


def test_execution_model_errors_reenter_task_attempt_flow(tmp_path):
    env, state_dir = _scenario_env(tmp_path, "execution_model_error")
    result = subprocess.run(
        _scenario_args(tmp_path, "execution_model_error"),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (state_dir / "execute.count").read_text() == "4"
    state = json.loads((tmp_path / ".ai-task-runner/state.json").read_text())
    assert state["tasks"][0]["attempts"] == 4
    assert state["completed"] is True


def test_repeated_no_change_model_errors_defer_to_file_validator(tmp_path):
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import argparse\n"
        "p=argparse.ArgumentParser();"
        "p.add_argument('--project-root');"
        "p.add_argument('--state-file');"
        "p.parse_args();"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    env, state_dir = _scenario_env(
        tmp_path,
        "execution_model_error_no_change_forever",
    )
    result = subprocess.run(
        _scenario_args(
            tmp_path,
            "execution_model_error_no_change_forever",
            validator=validator,
        ),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (state_dir / "execute.count").read_text() == "3"
    state = json.loads((tmp_path / ".ai-task-runner/state.json").read_text())
    assert state["tasks"][0]["status"] == "completed"
    assert "Deferring this task" in state["tasks"][0]["last_review"]["reason"]
    assert state["completed"] is True


def test_execution_error_after_project_change_goes_to_review(tmp_path):
    env, state_dir = _scenario_env(tmp_path, "execution_error_after_change")
    result = subprocess.run(
        _scenario_args(tmp_path, "execution_error_after_change"),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (state_dir / "execute.count").read_text() == "1"
    assert (state_dir / "review.count").read_text() == "1"
    state = json.loads((tmp_path / ".ai-task-runner/state.json").read_text())
    assert state["tasks"][0]["attempts"] == 1
    assert state["completed"] is True


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
    assert (state_dir / "execute.count").read_text() == "1"
    assert (state_dir / "review.count").read_text() == "1"


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


def test_repeated_validator_failure_enters_repair_mode(tmp_path):
    validator = tmp_path / "validator.py"
    validator.write_text(
        """import argparse
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--project-root'); p.add_argument('--state-file'); a=p.parse_args()
root=Path(a.project_root)
if not (root/'repaired.txt').exists():
    print('same validator failure')
    raise SystemExit(1)
print('PASS')
""",
        encoding="utf-8",
    )
    env, state_dir = _scenario_env(tmp_path, "validator_repair")
    result = subprocess.run(
        _scenario_args(
            tmp_path,
            "validator_repair",
            validator=validator,
            extra=["--max-cycles", "4"],
        ),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "repaired.txt").read_text(encoding="utf-8") == "done"
    assert (state_dir / "execute.count").read_text() == "3"
    state = json.loads((tmp_path / ".ai-task-runner/state.json").read_text())
    assert state["completed"] is True
    assert state["stage"] == "completed"
    assert state["stage_started_at"] > 0
    assert state["last_activity_at"] >= state["stage_started_at"]
    assert state["validator_failure_count"] == 0


def test_many_validator_cycles_soak_finishes_with_bounded_state(tmp_path):
    validator = tmp_path / "validator.py"
    validator.write_text(
        """import argparse
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--project-root'); p.add_argument('--state-file'); a=p.parse_args()
root=Path(a.project_root)
counter=root/'.validator.count'
n=int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n+1))
if n < 14:
    print('soak failure')
    raise SystemExit(1)
print('PASS')
""",
        encoding="utf-8",
    )
    cmd = f'"{sys.executable}" "{ROOT / "tests/fake_agent.py"}"'
    args = [sys.executable, str(ROOT / "ai_task_runner.py"), "--backend", "qwen", "--goal", "x",
            "--project-root", str(tmp_path), "--validator", str(validator), "--command", cmd,
            "--retry-delay", "0", "--retry-wait", "0", "--retry-max-wait", "0",
            "--max-cycles", "20"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    state_file = tmp_path / ".ai-task-runner/state.json"
    state = json.loads(state_file.read_text())
    assert state["completed"] is True
    assert state["cycle"] == 15
    assert state_file.stat().st_size < 200_000



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


def _run_session_replacement_case(tmp_path, failure_message: str = ""):
    state_dir = Path(tempfile.mkdtemp(prefix=f"{tmp_path.name}-session-", dir=tmp_path.parent))
    env = {**os.environ, "SESSION_TEST_STATE_DIR": str(state_dir)}
    if failure_message:
        env["SESSION_FAILURE_MESSAGE"] = failure_message
    command = f'"{sys.executable}" "{ROOT / "tests/session_expired_agent.py"}"'
    work = tmp_path / ".ai-task-runner"
    work.mkdir()
    (work / "state.json").write_text(json.dumps({
        "run_id": "session-test",
        "goal": "x",
        "project_root": str(tmp_path),
        "cycle": 1,
        "current": 0,
        "tasks": [{
            "id": "c01-t001",
            "title": "Create marker",
            "description": "Create done.txt",
            "acceptance_criteria": ["done.txt exists"],
            "status": "pending",
            "attempts": 0,
            "last_output": "",
            "last_review": None,
            "progress_key": "",
            "stagnant_attempts": 0,
        }],
        "validator_output": "",
        "completed": False,
        "agent_session_id": "old-session",
    }), encoding="utf-8")
    args = [
        sys.executable,
        str(ROOT / "ai_task_runner.py"),
        "--backend",
        "qwen",
        "--project-root",
        str(tmp_path),
        "--validator",
        "ai",
        "--command",
        command,
        "--resume",
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


def test_expired_session_is_replaced_and_work_continues(tmp_path):
    _run_session_replacement_case(tmp_path)


def test_loop_detection_session_is_replaced_and_work_continues(tmp_path):
    _run_session_replacement_case(
        tmp_path,
        "Loop detection halted the run (consecutive_identical_tool_calls)",
    )


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
        bounded_text,
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

    bounded = bounded_text("FIRST" + "A" * 10000 + "LAST", 2000)
    assert "FIRST" in bounded
    assert "LAST" in bounded
    assert "omitted" in bounded
    assert len(bounded) <= 2000


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
    state.validator_output = "unexpected output:\nold value"
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
    assert "the actual bad value to change away from" in execute
    assert "fix the program behavior that produces it" in execute


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

    expected = [*args]
    for tool_name in runner_core.QWEN_PLANNING_EXCLUDED_TOOLS:
        expected.extend(["--exclude-tools", tool_name])
    assert runner_core.planning_agent_args("qwen", args) == expected
    assert runner_core.planning_agent_args("opencode", args) == args


def test_qwen_runtime_args_exclude_runner_owned_todo_tool():
    import runner_core

    args = ["--approval-mode", "yolo"]

    expected = [*args]
    for tool_name in runner_core.QWEN_RUNTIME_EXCLUDED_TOOLS:
        expected.extend(["--exclude-tools", tool_name])
    assert runner_core.runtime_agent_args("qwen", args) == expected
    assert runner_core.runtime_agent_args("opencode", args) == args


def test_qwen_args_default_to_yolo():
    import runner_core

    assert runner_core.planning_agent_args("qwen", [])[0] == "--yolo"
    assert runner_core.runtime_agent_args("qwen", [])[0] == "--yolo"
    assert "--yolo" not in runner_core.runtime_agent_args(
        "qwen",
        ["--approval-mode", "yolo"],
    )
