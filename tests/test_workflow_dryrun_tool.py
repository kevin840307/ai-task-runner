from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "workflow_dryrun.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_system_mixed_dryrun_reaches_closure():
    result = run(
        "runner/workflow/system/mixed.yaml",
        "--scenario",
        "dryrunexample/system_mixed_scenario.yaml",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DRYRUN_PASSED" in result.stdout
    assert "review" in result.stdout
    assert "validate_file" in result.stdout


def test_custom_workflow_dryrun_reaches_closure_after_max_results():
    result = run(
        "dryrunexample/workflow.yaml",
        "--scenario",
        "dryrunexample/custom_scenario.yaml",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DRYRUN_PASSED" in result.stdout
    assert result.stdout.count("check") >= 3


def test_dryrun_detects_non_converging_workflow(tmp_path: Path):
    workflow = tmp_path / "loop_workflow.yaml"
    workflow.write_text(
        """stages:
  check:
    status: Check
    recover: [fix]
  fix:
    status: Fix
  final:
    validator: ai
    status: Final
flow:
  - check
  - final
""",
        encoding="utf-8",
    )
    scenario = tmp_path / "loop.yaml"
    scenario.write_text(
        """default: pass
stages:
  check: fail
""",
        encoding="utf-8",
    )
    result = run(
        str(workflow),
        "--scenario",
        str(scenario),
        "--max-steps",
        "8",
    )
    assert result.returncode == 1
    assert "DRYRUN_FAILED" in result.stdout
    assert "did not converge" in result.stdout


def test_dryrun_matrix_covers_system_recovery_paths():
    result = run("runner/workflow/system/mixed.yaml", "--matrix")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WORKFLOW_CLOSED" in result.stdout
    assert "review FAIL -> recover -> closure" in result.stdout
    assert "validate_file FAIL -> recover -> closure" in result.stdout
    assert "validate_ai FAIL -> recover -> closure" in result.stdout


def test_dryrun_matrix_covers_custom_recovery_paths():
    result = run("dryrunexample/workflow.yaml", "--matrix")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WORKFLOW_CLOSED" in result.stdout
    assert "check FAIL -> recover -> closure" in result.stdout


def test_dryrun_rejects_invalid_workflow_options(tmp_path: Path):
    cases = {
        "unknown_option": """stages:\n  work:\n    bogus: true\n  final:\n    validator: ai\nflow: [work, final]\n""",
        "bad_max_results": """stages:\n  check:\n    max_results: 0\n    recover: [fix]\n  fix: {}\n  final:\n    validator: ai\nflow: [check, final]\n""",
        "max_results_without_recover": """stages:\n  check:\n    max_results: 2\n  final:\n    validator: ai\nflow: [check, final]\n""",
        "bad_fresh_failures": """stages:\n  check:\n    fresh_after_same_failures: 0\n    recover: [fix]\n  fix: {}\n  final:\n    validator: ai\nflow: [check, final]\n""",
        "required_passes_gt_runs": """stages:\n  final:\n    validator: ai\n    runs: 2\n    required_passes: 3\nflow: [final]\n""",
        "unknown_stage": """stages:\n  final:\n    validator: ai\nflow: [missing, final]\n""",
        "bad_validator_type": """stages:\n  final:\n    type: command\n    validator: ai\nflow: [final]\n""",
    }
    for name, text in cases.items():
        workflow = tmp_path / f"{name}.yaml"
        workflow.write_text(text, encoding="utf-8")
        result = run(str(workflow))
        assert result.returncode == 2, f"{name}: {result.stdout}{result.stderr}"
        assert "DRYRUN_ERROR" in result.stderr, name


def test_dryrun_supports_generic_task_producer():
    import json

    result = run("examples/custom_workflow_latest.yaml", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["completed"] is True
    assert [item["stage"] for item in payload["transitions"]] == [
        "discover_tasks", "execute", "review", "done"
    ]


def test_dryrun_json_contract_is_machine_readable():
    import json

    result = run("runner/workflow/system/file.yaml", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["completed"] is True
    assert payload["workflow_size"] == 4
    assert [item["stage"] for item in payload["transitions"]] == [
        "planning", "execute", "review", "validate_file"
    ]


def test_dryrun_matrix_json_reports_repeat_and_restart_paths(tmp_path: Path):
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """
stages:
  start:
    type: command
    command: [python, -c, "print('START')"]
  challenge:
    type: command
    command: [python, -c, "print('CHALLENGE')"]
  repair:
    type: command
    command: [python, -c, "print('REPAIR')"]
  restartable:
    type: command
    command: [python, -c, "print('RESTARTABLE')"]
flow:
  - start
  - stage: challenge
    repeat: 3
    recover: [repair]
  - stage: restartable
    restart_at: start
""".lstrip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(TOOL), str(workflow), "--matrix", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["closed"] is True
    assert payload["features"]["repeat"] == 1
    assert payload["features"]["restart_at"] == 1
    names = {item["name"] for item in payload["cases"]}
    assert "challenge FAIL x3 -> bounded recover -> closure" in names
    assert "restartable FAIL -> restart_at -> closure" in names



def test_dryrun_matrix_proves_fresh_session_threshold(tmp_path: Path):
    workflow = tmp_path / "fresh.yaml"
    workflow.write_text(
        """stages:
  check:
    type: command
    command: [python, -c, "print('CHECK')"]
    fresh_after_same_failures: 2
    recover: [repair]
  repair:
    type: command
    command: [python, -c, "print('REPAIR')"]
flow:
  - check
""",
        encoding="utf-8",
    )
    result = run(str(workflow), "--matrix", "--json")
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["features"]["fresh_after_same_failures"] == 1
    fresh = next(case for case in payload["cases"] if "fresh session" in case["name"])
    assert fresh["passed"] is True
    assert fresh["expected_fresh_sessions"] == 1
    assert fresh["fresh_sessions"] >= 1


def test_dryrun_handles_twelve_stage_composable_sop(tmp_path: Path):
    stages = [
        f"  s{i:02d}:\n    type: command\n    command: [python, -c, \"print('S{i:02d}')\"]"
        for i in range(1, 13)
    ]
    stages.append("  repair:\n    type: command\n    command: [python, -c, \"print('REPAIR')\"]")
    flow = []
    for i in range(1, 13):
        if i == 5:
            flow.extend(["  - stage: s05", "    repeat: 3", "    recover: [repair]"])
        elif i == 9:
            flow.extend(["  - stage: s09", "    recover: [repair]"])
        elif i == 10:
            flow.extend(["  - stage: s10", "    restart_at: s08"])
        else:
            flow.append(f"  - s{i:02d}")
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "stages:\n" + "\n".join(stages) + "\nflow:\n" + "\n".join(flow) + "\n",
        encoding="utf-8",
    )

    completed = run(str(workflow), "--matrix", "--json")
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["closed"] is True
    assert payload["features"]["stages"] == 12
    assert payload["features"]["repeat"] == 1
    assert payload["features"]["recover"] >= 2
    assert payload["features"]["restart_at"] == 1


def test_system_custom_skill_prompt_review_chain_linear_dryrun_closes():
    result = run("runner/workflow/custom/skill_prompt_review_chain.yaml", "--matrix", "--json")
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["closed"] is True
    assert payload["features"]["task_scope"] is False
    assert payload["features"]["task_producer"] is False
    assert any(case["name"] == "validate_file FAIL -> recover -> closure" for case in payload["cases"])
