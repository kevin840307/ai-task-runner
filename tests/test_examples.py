from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from runner.config.runtime import RuntimeConfig
from runner.script_loader import load_yaml_script
from runner.script_runner import build_script_item_config

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
EXPECTED = {
    "01_basic_python_validator",
    "02_repair_cycle",
    "03_ai_validator_voting",
    "04_mixed_validation",
    "05_ai_quality_repair",
    "06_yaml_driven_tool",
    "07_blackbox_medium",
    "08_config_driven_data_pipeline",
    "09_config_environment_auditor",
    "10_skill_prompt_review_workflow",
    "11_regression_workflow_demo",
}


def test_example_inventory_and_batch_launcher():
    available = {p.name for p in EXAMPLES.iterdir() if p.is_dir()}
    assert EXPECTED <= available
    assert (EXAMPLES / "examples.yaml").is_file()
    assert (EXAMPLES / "run_examples.bat").is_file()
    for name in EXPECTED:
        folder = EXAMPLES / name
        assert (folder / "project").is_dir()
        project = folder / "project"
        assert (project / "prompt.md").is_file()
        assert (project / ".ai-task-runner.yaml").is_file()
        assert (folder / "run_example.bat").is_file()


def test_example_python_files_compile():
    files = sorted(EXAMPLES.rglob("*.py"))
    assert files
    for path in files:
        subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def test_examples_yaml_runs_01_to_11_with_per_item_project_roots():
    script = EXAMPLES / "examples.yaml"
    data = yaml.safe_load(script.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 11
    for index, item in enumerate(data, 1):
        prefix = f"{index:02d}_"
        goal_file = item.get("goal_file")
        assert isinstance(goal_file, str) and goal_file.strip()
        assert (EXAMPLES / goal_file).is_file()
        project_root = item.get("project_root")
        assert isinstance(project_root, str) and Path(project_root).parent.name.startswith(prefix)
        assert (EXAMPLES / project_root).is_dir()
        validator = item.get("validator")
        assert isinstance(validator, str) and validator.strip()
        if validator != "ai":
            assert (EXAMPLES / validator).is_file()
    assert data[2]["validator"] == "ai" and data[2]["ai_validator_count"] == 3
    for item in [data[2], data[3], data[4], data[7], data[8]]:
        assert item["ai_validator_count"] == 3
        assert "ai_validator_prompt" not in item
        prompt_file = item.get("ai_validator_prompt_file")
        assert isinstance(prompt_file, str) and (EXAMPLES / prompt_file).is_file()
    assert data[9]["workflow_file"] == "../tool/workflows/skill_prompt_review_chain.yaml"
    assert (EXAMPLES / data[9]["workflow_file"]).is_file()

    items = load_yaml_script(script)
    config = RuntimeConfig(project_root=str(EXAMPLES), script=str(script))
    workflow = build_script_item_config(config, items[9], 10).workflow
    assert [stage["name"] for stage in workflow] == [
        "run_prompt",
        "review",
        "run_prompt",
        "review",
        "run_prompt",
        "review",
        "validate_file",
    ]
    assert data[10]["workflow_file"] == "11_regression_workflow_demo/workflow.yaml"
    assert data[10]["validator"] == "ai"
    assert (EXAMPLES / data[10]["workflow_file"]).is_file()
    regression = build_script_item_config(config, items[10], 11).workflow
    assert [stage["name"] for stage in regression] == [
        "run_prompt", "review", "run_prompt", "grill_ai", "review",
        "run_prompt", "grill_ai", "review", "run_prompt", "review",
        "run_prompt", "review", "run_prompt", "review", "final_validate",
    ]


def test_validation_modes_example_maps_to_builtin_workflows():
    script = EXAMPLES / "validation_modes.yaml"
    items = load_yaml_script(script)
    config = RuntimeConfig(project_root=str(EXAMPLES), script=str(script))

    workflows = [
        [stage["name"] for stage in build_script_item_config(config, item, index).workflow]
        for index, item in enumerate(items, 1)
    ]

    assert workflows == [
        ["planning", "validate_file"],
        ["planning", "validate_ai"],
        ["planning", "validate_file", "validate_ai"],
    ]
    assert all("workflow_file" not in item for item in yaml.safe_load(script.read_text()))


def run_validator(name: str) -> subprocess.CompletedProcess[str]:
    folder = EXAMPLES / name
    return subprocess.run(
        [
            sys.executable,
            str(folder / "project" / "validation.py"),
            "--project-root",
            str(folder / "project"),
            "--state-file",
            str(folder / "unused-state.json"),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )


def test_starter_states_match_example_purpose():
    # These cases intentionally start incomplete or broken so the Runner has work to do.
    for name in (
        "01_basic_python_validator",
        "02_repair_cycle",
        "04_mixed_validation",
        "06_yaml_driven_tool",
        "07_blackbox_medium",
        "08_config_driven_data_pipeline",
        "09_config_environment_auditor",
        "10_skill_prompt_review_workflow",
    ):
        result = run_validator(name)
        assert result.returncode != 0, f"starter unexpectedly passed: {name}\n{result.stdout}"
        assert "VALIDATION_FAILED" in result.stdout

    # Example 05 deliberately hard-passes first; its AI semantic gate should catch the sample-specific starter.
    result = run_validator("05_ai_quality_repair")
    assert result.returncode == 0, result.stdout
    assert "VALIDATION_PASSED" in result.stdout


def test_ai_examples_have_visible_custom_prompts():
    for name in ("03_ai_validator_voting", "04_mixed_validation", "05_ai_quality_repair"):
        text = (EXAMPLES / name / "project" / "ai_validation.md").read_text(encoding="utf-8")
        assert len(text.splitlines()) >= 3


def test_blackbox_medium_validator_does_not_inspect_implementation_structure():
    text = (EXAMPLES / "07_blackbox_medium" / "project" / "validation.py").read_text(encoding="utf-8")
    assert "ast." not in text
    assert "inspect." not in text
    assert "class " not in text
    assert "line count" not in text.lower()
    assert "rglob(" not in text


def test_smoke_validators_keep_local_interface_contract():
    entries = []
    for path in (ROOT / "smoke").rglob("*.py"):
        if path.name in {"validator_interface.py", "common.py"}:
            continue
        if path.name in {"validator.py", "validation.py"} or path.name.endswith("_validator.py"):
            entries.append(path)
    assert entries
    for path in entries:
        text = path.read_text(encoding="utf-8")
        assert "validator_interface import" in text, path
        assert "ValidatorReport" in text, path
        assert (path.parent / "validator_interface.py").is_file(), path


def test_smoke_validator_interfaces_provide_actionable_json_diagnostics():
    interfaces = sorted((ROOT / "smoke").rglob("validator_interface.py"))
    assert interfaces
    for path in interfaces:
        text = path.read_text(encoding="utf-8")
        assert "def parse_json(" in text, path
        assert "traceback.format_exc" in text, path


def test_todo_cli_validator_checks_state_after_each_mutation():
    text = (ROOT / "smoke" / "qwen_todo_cli" / "validator.py").read_text(encoding="utf-8")
    assert "read_state(root,db,'after '+" in text
    assert "CLI list and stored JSON differ" in text


def test_python_example_validators_use_shared_validator_report():
    validators = sorted((EXAMPLES).glob("*/project/validation.py"))
    assert validators
    for path in validators:
        text = path.read_text(encoding="utf-8")
        assert "from ai_task_runner_validator import ValidatorReport" in text, path
        assert "ValidatorReport(" in text, path
        assert ".finish()" in text, path
        assert "print('VALIDATION_PASSED')" not in text, path
        assert "print('VALIDATION_FAILED')" not in text, path


def test_example_project_policies_protect_control_files():
    for name in EXPECTED:
        project = EXAMPLES / name / "project"
        policy = yaml.safe_load((project / ".ai-task-runner.yaml").read_text(encoding="utf-8"))
        protected = set(policy.get("protected_paths", []))
        assert "prompt.md" in protected
        if (project / "validation.py").is_file():
            assert "validation.py" in protected
            assert "ai_task_runner_validator.py" in protected
        if (project / "ai_validation.md").is_file():
            assert "ai_validation.md" in protected


def test_regression_workflow_demo_mock_contract():
    result = subprocess.run(
        [sys.executable, str(EXAMPLES / "11_regression_workflow_demo" / "test_demo.py")],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90,
    )
    assert result.returncode == 0, result.stdout
    assert "PASS regression workflow demo" in result.stdout


def test_example_temp_runner_copies_workspace_and_preserves_source(tmp_path, monkeypatch):
    from tool import example_temp_runner

    monkeypatch.setenv("AI_TASK_RUNNER_EXAMPLE_TEMP", str(tmp_path))
    original = EXAMPLES / "11_regression_workflow_demo" / "project" / "src" / "calculator.py"
    before = original.read_bytes()
    copied = example_temp_runner._copy_workspace("isolation")
    target = copied / "examples" / "11_regression_workflow_demo" / "project" / "src" / "calculator.py"
    target.write_text("changed only in temporary workspace\n", encoding="utf-8")
    assert original.read_bytes() == before
    assert target.read_bytes() != before


def test_example_temp_runner_selects_one_yaml_item(tmp_path, monkeypatch):
    from tool import example_temp_runner

    monkeypatch.setenv("AI_TASK_RUNNER_EXAMPLE_TEMP", str(tmp_path))
    copied = example_temp_runner._copy_workspace("selection")
    selected = example_temp_runner._select_example(copied, "11_regression_workflow_demo")
    data = yaml.safe_load(selected.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["project_root"] == "11_regression_workflow_demo/project"
    assert data[0]["workflow_file"] == "11_regression_workflow_demo/workflow.yaml"


def test_example_bats_use_shared_temp_runner():
    master = (EXAMPLES / "run_examples.bat").read_text(encoding="utf-8")
    assert "example_temp_runner.py" in master and "--all" in master
    for name in EXPECTED:
        text = (EXAMPLES / name / "run_example.bat").read_text(encoding="utf-8")
        assert "example_temp_runner.py" in text
        assert f'--example "{name}"' in text
