from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from runner.api import RunRequest, run

ROOT = Path(__file__).resolve().parents[1]


def command() -> str:
    return f'"{sys.executable}" "{ROOT / "tests/scenario_agent.py"}"'


def records(state_dir: Path) -> list[dict]:
    path = state_dir / "prompt-log.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def run_case(tmp_path, monkeypatch, scenario: str, *, backend="qwen", validator="ai", **kwargs):
    state_dir = tmp_path.parent / f"{tmp_path.name}-{scenario}-{backend}-state"
    monkeypatch.setenv("SCENARIO", scenario)
    monkeypatch.setenv("SCENARIO_STATE_DIR", str(state_dir))
    result = run(
        RunRequest(
            goal="Create the requested result",
            project_root=str(tmp_path),
            validator=validator,
            backend=backend,
            command=command(),
            stage_retries=-1,
            retry_delay=0,
            retry_max_delay=0,
            agent_idle_after_change_timeout=0,
            **kwargs,
        )
    )
    return result, records(state_dir)


@pytest.mark.parametrize("backend", ["qwen", "opencode"])
def test_happy_path_uses_the_same_runner_contract_for_both_backends(
    tmp_path, monkeypatch, backend
):
    result, rows = run_case(tmp_path, monkeypatch, "happy_path", backend=backend)

    assert result.completed is True
    stages = [row["stage"] for row in rows]
    assert "execute" in stages
    assert "review" in stages
    assert stages.count("validator") == 3
    assert all(row["stage"] != "unknown" for row in rows)


@pytest.mark.parametrize("backend", ["qwen", "opencode"])
@pytest.mark.parametrize("scenario", ["execution_model_error", "api_503"])
def test_technical_failures_use_shared_stage_retry_for_both_backends(
    tmp_path, monkeypatch, backend, scenario
):
    result, rows = run_case(
        tmp_path,
        monkeypatch,
        scenario,
        backend=backend,
        final_ai_validations=1,
        final_ai_required_passes=1,
    )

    assert result.completed is True
    attempts = [row for row in rows if row["stage"] == "execute"]
    assert len(attempts) >= 2
    assert any(row["resumed"] for row in attempts[1:])


@pytest.mark.parametrize("backend", ["qwen", "opencode"])
@pytest.mark.parametrize("worker_policy", ["main", "role", "fresh"])
def test_dynamic_handoff_uses_same_runtime_contract_for_both_backends(
    tmp_path, monkeypatch, backend, worker_policy
):
    workflow = tmp_path / "dynamic.workflow.yaml"
    workflow.write_text(
        f"""stages:
  coordinator:
    type: handoff
    targets: [worker, final_validate]
    session_policy: role
  worker:
    type: base
    prompt: common/dynamic_worker.md
    instructions: Create done.txt and return.
    session_policy: {worker_policy}
    mode: write
    track_changes: true
    routes:
      pass: coordinator
  final_validate:
    type: ai_validator
    validator: ai
    session_policy: fresh
    runs: 1
    required_passes: 1
    routes:
      pass: done
      fail: coordinator
flow:
  - coordinator
  - worker
  - final_validate
""",
        encoding="utf-8",
    )

    result, rows = run_case(
        tmp_path,
        monkeypatch,
        "dynamic_handoff",
        backend=backend,
        workflow_file=str(workflow),
        final_ai_validations=1,
        final_ai_required_passes=1,
    )

    assert result.completed is True
    assert all(row["stage"] != "unknown" for row in rows)
    assert [row["stage"] for row in rows] == [
        "handoff",
        "execute",
        "handoff",
        "validator",
    ]
    assert (tmp_path / "done.txt").is_file()


@pytest.mark.parametrize("backend", ["qwen", "opencode"])
def test_review_fail_result_edge_routes_back_to_execute(tmp_path, monkeypatch, backend):
    result, rows = run_case(
        tmp_path,
        monkeypatch,
        "review_retry",
        backend=backend,
        final_ai_validations=1,
        final_ai_required_passes=1,
    )

    assert result.completed is True
    assert sum(row["stage"] == "review" for row in rows) >= 2
    assert sum(row["stage"] == "execute" for row in rows) >= 2


def test_multi_task_same_session_sends_only_new_todo_context(tmp_path, monkeypatch):
    state_dir = tmp_path.parent / f"{tmp_path.name}-multi-context-state"
    monkeypatch.setenv("SCENARIO", "multi_task_plan")
    monkeypatch.setenv("SCENARIO_STATE_DIR", str(state_dir))
    validator = tmp_path / "validator.py"
    validator.write_text(
        "from pathlib import Path\n"
        "import argparse\n"
        "p=argparse.ArgumentParser(); p.add_argument('--project-root'); p.add_argument('--state-file'); a=p.parse_args()\n"
        "r=Path(a.project_root); raise SystemExit(0 if (r/'first.txt').exists() and (r/'second.txt').exists() else 5)\n",
        encoding="utf-8",
    )

    result = run(
        RunRequest(
            goal="Create first.txt then second.txt",
            project_root=str(tmp_path),
            validator=str(validator),
            backend="qwen",
            command=command(),
            stage_retries=-1,
            retry_delay=0,
            retry_max_delay=0,
        )
    )

    assert result.completed is True
    execute = [row for row in records(state_dir) if row["stage"] == "execute"]
    assert len(execute) == 2
    assert execute[0]["resumed"] is True
    assert execute[1]["resumed"] is True
    assert execute[1]["prompt"].find("RUNNER_SHARED_STAGE_CONTROL") >= 0
    assert "mode: continue" in execute[1]["prompt"]
    assert '"title": "Create second marker"' in execute[1]["prompt"]
    assert "Goal (global constraints only):" not in execute[1]["prompt"]


def test_review_feedback_continuation_sends_only_new_evidence(tmp_path, monkeypatch):
    result, rows = run_case(
        tmp_path,
        monkeypatch,
        "review_retry",
        final_ai_validations=1,
        final_ai_required_passes=1,
    )

    assert result.completed is True
    reviews = [row for row in rows if row["stage"] == "review"]
    executes = [row for row in rows if row["stage"] == "execute"]
    assert len(reviews) >= 2
    assert reviews[1]["resumed"] is True
    assert reviews[1]["prompt"].find("RUNNER_SHARED_STAGE_CONTROL") >= 0
    assert "mode: continue" in reviews[1]["prompt"]
    assert "Evidence order:" not in reviews[1]["prompt"]
    assert any(
        row["prompt"].find("RUNNER_SHARED_STAGE_CONTROL") >= 0
        and "Review missing_items:" in row["prompt"]
        for row in executes[1:]
    )


def test_builtin_prompts_live_in_the_common_prompt_category():
    root = ROOT / "runner" / "assets" / "prompts" / "common"
    for name in ("planning.md", "execution.md", "review.md", "ai_validator.md"):
        assert (root / name).is_file()
    assert not (ROOT / "runner" / "workflows").exists()
    assert not (ROOT / "runner" / "prompts").exists()
