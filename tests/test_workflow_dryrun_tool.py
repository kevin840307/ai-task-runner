from __future__ import annotations

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


def test_builtin_mixed_dryrun_reaches_closure():
    result = run(
        "runner/workflow/builtin/mixed.yaml",
        "--scenario",
        "dryrunexample/builtin_mixed_scenario.yaml",
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


def test_dryrun_matrix_covers_builtin_recovery_paths():
    result = run("runner/workflow/builtin/mixed.yaml", "--matrix")
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
        "no_validator": """stages:\n  work: {}\nflow: [work]\n""",
        "bad_validator_type": """stages:\n  final:\n    type: python\n    validator: ai\nflow: [final]\n""",
    }
    for name, text in cases.items():
        workflow = tmp_path / f"{name}.yaml"
        workflow.write_text(text, encoding="utf-8")
        result = run(str(workflow))
        assert result.returncode == 2, f"{name}: {result.stdout}{result.stderr}"
        assert "DRYRUN_ERROR" in result.stderr, name
