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
        timeout=30,
        check=False,
    )


def test_builtin_mixed_dryrun_reaches_closure_through_result_edges():
    result = run(
        "runner/assets/workflows/mixed.yaml",
        "--scenario",
        "dryrunexample/system_mixed_scenario.yaml",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DRYRUN_PASSED" in result.stdout
    assert result.stdout.count("review") >= 2
    assert result.stdout.count("validate_file") >= 2


def test_custom_result_edge_loop_reaches_closure():
    result = run(
        "dryrunexample/workflow.yaml",
        "--scenario",
        "dryrunexample/custom_scenario.yaml",
        "--json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["completed"] is True
    assert [item["stage"] for item in payload["transitions"]] == [
        "work", "check", "work", "check", "final"
    ]


def test_dryrun_detects_non_converging_result_edge_loop(tmp_path: Path):
    workflow = tmp_path / "loop.yaml"
    workflow.write_text(
        """stages:
  check:
    type: base
    profile: review
    max_failures: null
    routes:
      fail: check
flow:
  - check
""",
        encoding="utf-8",
    )
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("stages:\n  check: fail\n", encoding="utf-8")

    result = run(str(workflow), "--scenario", str(scenario), "--max-steps", "8")

    assert result.returncode == 1
    assert "did not converge" in result.stdout


def test_dryrun_matrix_covers_semantic_routes_and_safe_stop():
    result = run("runner/assets/workflows/mixed.yaml", "--matrix", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)

    assert payload["closed"] is True
    assert payload["features"]["routes"] >= 3
    names = {case["name"] for case in payload["cases"]}
    assert any(
        name.startswith("planning__g1__task_001_review FAIL -> ")
        and name.endswith("__task_001_execute -> closure")
        for name in names
    )
    assert "validate_file FAIL -> planning -> closure" in names
    assert "validate_ai FAIL -> planning -> closure" in names
    assert "planning ERROR -> stop" in names


def test_dryrun_supports_custom_task_producer():
    result = run("examples/custom_workflow_latest.yaml", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)

    assert payload["completed"] is True
    stages = [item["stage"] for item in payload["transitions"]]
    assert stages[0] == "discover_tasks"
    assert stages[-1] == "done"
    assert any(name.startswith("discover_tasks__g") for name in stages[1:-1])


def test_dryrun_rejects_removed_legacy_routing_fields(tmp_path: Path):
    workflow = tmp_path / "legacy.yaml"
    workflow.write_text(
        """stages:
  work:
    type: base
    profile: review
    recover: [repair]
  repair:
    type: base
    profile: execute
flow: [work]
""",
        encoding="utf-8",
    )

    result = run(str(workflow))

    assert result.returncode == 2
    assert "DRYRUN_ERROR" in result.stderr
    assert "unknown options" in result.stderr


def test_dryrun_rejects_invalid_route_target(tmp_path: Path):
    workflow = tmp_path / "bad-route.yaml"
    workflow.write_text(
        """stages:
  work:
    type: base
    profile: review
    routes:
      fail: missing
flow: [work]
""",
        encoding="utf-8",
    )

    result = run(str(workflow))

    assert result.returncode == 2
    assert "unknown stage" in result.stderr


def test_ralphy_minimal_execute_validate_loop_closes():
    result = run(
        "runner/assets/workflows/ralphy_ai_validate.yaml",
        "--matrix",
        "--json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)

    assert payload["closed"] is True
    assert any(
        case["name"] == "validate_ai FAIL -> ralphy -> closure"
        for case in payload["cases"]
    )


def test_dryrun_json_contract_is_small_and_machine_readable():
    result = run("runner/assets/workflows/file.yaml", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)

    assert set(payload) == {
        "valid", "completed", "workflow", "from_stage", "executions", "error", "cycle", "stage", "transitions"
    }
    assert payload["valid"] is True
    assert payload["completed"] is True
    stages = [item["stage"] for item in payload["transitions"]]
    assert stages[0] == "planning"
    assert stages[-1] == "validate_file"
    assert any(name.endswith("__task_001_execute") for name in stages)
    assert any(name.endswith("__task_001_review") for name in stages)


def test_dynamic_handoff_matrix_exercises_selected_role_failures():
    result = run("runner/assets/workflows/dynamic_handoff.yaml", "--matrix", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["closed"] is True

    cases = {item["name"]: item for item in payload["cases"]}
    role_fail = cases["requirements_analyst FAIL -> stop"]
    role_error = cases["requirements_analyst ERROR -> stop"]
    assert role_fail["passed"] is True
    assert role_error["passed"] is True
    assert role_fail["executions"] == 2
    assert role_error["executions"] == 2


def test_dynamic_handoff_builtin_dryrun_reaches_final_validation():
    result = run("runner/assets/workflows/dynamic_handoff.yaml", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["completed"] is True
    assert [item["stage"] for item in payload["transitions"]] == [
        "coordinator", "final_validate"
    ]




def test_dryrun_matrix_reaches_branch_only_stage_before_injecting_failure(tmp_path: Path):
    workflow = tmp_path / "branch.yaml"
    workflow.write_text(
        """stages:
  gate:
    type: base
    profile: review
    routes:
      fail: branch
      pass: direct
  branch:
    type: base
    profile: generic
  direct:
    type: base
    profile: generic
flow:
  - gate
  - branch
  - direct
""",
        encoding="utf-8",
    )

    result = run(str(workflow), "--matrix", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["closed"] is True
    cases = {case["name"]: case for case in payload["cases"]}
    assert cases["branch FAIL -> stop"]["passed"] is True
    assert cases["branch FAIL -> stop"]["executions"] == 2


def test_dryrun_matrix_ignores_static_stage_that_is_unreachable_by_any_result_edge(tmp_path: Path):
    workflow = tmp_path / "unreachable.yaml"
    workflow.write_text(
        """stages:
  gate:
    type: base
    profile: review
    routes:
      pass: worker
      fail: worker
  dead:
    type: handoff
    targets: [worker]
  worker:
    type: base
    profile: generic
flow:
  - gate
  - dead
  - worker
""",
        encoding="utf-8",
    )

    result = run(str(workflow), "--matrix", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["closed"] is True
    names = {case["name"] for case in payload["cases"]}
    assert not any(name.startswith("dead ") for name in names)



def test_dryrun_exercises_max_cycle_exhaustion(tmp_path: Path):
    workflow = tmp_path / "loop.yaml"
    workflow.write_text(
        """
stages:
  a:
    type: base
    profile: generic
  b:
    type: base
    profile: generic
    routes:
      fail: a
flow: [a, b]
""",
        encoding="utf-8",
    )
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text(
        """
stages:
  a: pass
  b: fail
""",
        encoding="utf-8",
    )

    result = run(
        str(workflow),
        "--scenario", str(scenario),
        "--max-cycles", "2",
        "--max-steps", "20",
        "--json",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["completed"] is False
    assert payload["stage"] == "max_cycles_exhausted"
    assert payload["cycle"] == 3



def test_dryrun_from_stage_skips_prior_stages_and_reuses_flow_engine(tmp_path: Path):
    workflow = tmp_path / "from-stage.yaml"
    workflow.write_text(
        """
stages:
  first:
    type: base
    profile: generic
  middle:
    type: base
    profile: generic
  final:
    type: base
    profile: generic
flow: [first, middle, final]
""",
        encoding="utf-8",
    )

    result = run(
        str(workflow),
        "--from-stage", "middle",
        "--json",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["from_stage"] == "middle"
    assert [item["stage"] for item in payload["transitions"]] == ["middle", "final"]
    assert payload["completed"] is True


def test_dryrun_from_stage_still_obeys_semantic_fail_routing(tmp_path: Path):
    workflow = tmp_path / "from-stage-fail.yaml"
    workflow.write_text(
        """
stages:
  first:
    type: base
    profile: generic
  review:
    type: base
    profile: review
    routes:
      fail: fix
  fix:
    type: base
    profile: generic
  final:
    type: base
    profile: generic
flow: [first, review, fix, final]
""",
        encoding="utf-8",
    )
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("stages:\n  review: fail\n", encoding="utf-8")

    result = run(
        str(workflow),
        "--from-stage", "review",
        "--scenario", str(scenario),
        "--json",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert [item["stage"] for item in payload["transitions"]] == ["review", "fix", "final"]
    assert [item["status"] for item in payload["transitions"]] == ["fail", "pass", "pass"]


def test_dryrun_from_stage_rejects_unknown_stage(tmp_path: Path):
    workflow = tmp_path / "unknown-stage.yaml"
    workflow.write_text(
        """
stages:
  only:
    type: base
    profile: generic
flow: [only]
""",
        encoding="utf-8",
    )

    result = run(str(workflow), "--from-stage", "missing", "--json")

    assert result.returncode == 2
    assert "unknown --from-stage: missing" in result.stderr


def test_dryrun_plan_children_preserve_stage_backend_model_override(tmp_path: Path):
    from runner.workflow.loader import load_workflow
    from tool.workflow_dryrun import Scenario, _close, _execute

    workflow_file = tmp_path / "plan-backend.yaml"
    workflow_file.write_text(
        """
stages:
  planning:
    type: plan
    backend: opencode
    model: provider/model-x
  final:
    type: command
    command: ["{python}", "-c", "print('done')"]
flow:
  - planning
  - final
""".lstrip(),
        encoding="utf-8",
    )

    workflow = load_workflow(workflow_file)
    ctx, _executor, error = _execute(workflow, Scenario(), 100)
    try:
        assert error == ""
        children = [
            item for item in ctx.state.expanded_workflow
            if item.get("_dynamic_parent") == "planning"
        ]
        assert children
        assert all(item.get("backend") == "opencode" for item in children)
        assert all(item.get("model") == "provider/model-x" for item in children)
    finally:
        _close(ctx)
