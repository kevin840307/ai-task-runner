from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from runner.api import RunRequest, run

ROOT = Path(__file__).resolve().parents[1]


def command() -> str:
    return f'"{sys.executable}" "{ROOT / "tests/scenario_agent.py"}"'


def records(path: Path) -> list[dict]:
    log = path / "prompt-log.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def run_case(tmp_path, monkeypatch, scenario: str, *, validator="ai", **kwargs):
    state_dir = tmp_path.parent / f"{tmp_path.name}-{scenario}-state"
    monkeypatch.setenv("SCENARIO", scenario)
    monkeypatch.setenv("SCENARIO_STATE_DIR", str(state_dir))
    result = run(
        RunRequest(
            goal="Create requested result",
            project_root=str(tmp_path),
            validator=validator,
            backend="qwen",
            command=command(),
            retry_delay=0,
            retry_max_delay=0,
            agent_idle_after_change_timeout=0,
            **kwargs,
        )
    )
    return result, records(state_dir)


def validator(path: Path) -> Path:
    path.write_text(
        textwrap.dedent(
            """            import argparse
            from pathlib import Path
            p=argparse.ArgumentParser()
            p.add_argument("--project-root")
            p.add_argument("--state-file")
            a,_=p.parse_known_args()
            raise SystemExit(0 if (Path(a.project_root)/"done.txt").exists() else 5)
            """
        ),
        encoding="utf-8",
    )
    return path


def test_ai_workflow_closes_end_to_end(tmp_path, monkeypatch):
    result, rows = run_case(tmp_path, monkeypatch, "happy_path")
    assert result.completed
    assert (tmp_path / "done.txt").is_file()
    assert {"execute", "review", "validator"} <= {row["stage"] for row in rows}


def test_file_workflow_closes_end_to_end(tmp_path, monkeypatch):
    path = validator(tmp_path / "validator.py")
    result, rows = run_case(tmp_path, monkeypatch, "happy_path", validator=str(path))
    assert result.completed
    assert "validator" not in {row["stage"] for row in rows}


def test_review_fail_routes_back_to_execute(tmp_path, monkeypatch):
    result, rows = run_case(tmp_path, monkeypatch, "review_retry")
    assert result.completed
    assert sum(row["stage"] == "execute" for row in rows) >= 2
    assert sum(row["stage"] == "review" for row in rows) >= 2


def test_technical_failure_retries_inside_same_stage_and_rotates_session(tmp_path, monkeypatch):
    result, rows = run_case(tmp_path, monkeypatch, "execution_model_error")
    assert result.completed
    attempts = [row for row in rows if row["stage"] == "execute"]
    assert len(attempts) >= 4
    assert any(row["resumed"] for row in attempts[1:])
    assert any(not row["resumed"] for row in attempts[2:])


def test_transient_api_failure_retries_until_service_returns(tmp_path, monkeypatch):
    result, rows = run_case(tmp_path, monkeypatch, "api_503")
    assert result.completed
    assert sum(row["stage"] == "execute" for row in rows) >= 4


def test_yaml_list_uses_same_runtime_contract(tmp_path, monkeypatch):
    state_dir = tmp_path.parent / "yaml-state"
    monkeypatch.setenv("SCENARIO", "happy_path")
    monkeypatch.setenv("SCENARIO_STATE_DIR", str(state_dir))
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: Create requested result\n  validator: ai\n"
        "- prompt: Create requested result again\n  validator: ai\n",
        encoding="utf-8",
    )
    result = run(
        RunRequest(
            project_root=str(tmp_path),
            script=str(script),
            backend="qwen",
            command=command(),
            retry_delay=0,
            retry_max_delay=0,
            agent_idle_after_change_timeout=0,
        )
    )
    assert result.completed
    assert len(result.states) == 2


def test_final_ai_votes_are_fresh_sessions(tmp_path, monkeypatch):
    result, rows = run_case(
        tmp_path,
        monkeypatch,
        "happy_path",
        final_ai_validations=3,
        final_ai_required_passes=2,
    )
    assert result.completed
    votes = [row for row in rows if row["stage"] == "validator"]
    assert len(votes) == 3
    assert all(not row["resumed"] for row in votes)


def test_protected_file_restore_then_retry(tmp_path, monkeypatch):
    protected = tmp_path / "protected.txt"
    protected.write_text("original", encoding="utf-8")
    monkeypatch.setenv("PROTECTED_PATH", str(protected))
    result, rows = run_case(
        tmp_path,
        monkeypatch,
        "protected_retry",
        protect_files=[str(protected)],
    )
    assert result.completed
    assert protected.read_text(encoding="utf-8") == "original"
    assert sum(row["stage"] == "execute" for row in rows) >= 2
