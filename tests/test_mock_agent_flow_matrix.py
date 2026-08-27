from __future__ import annotations

import json
import sys

import pytest
from collections import Counter
from pathlib import Path

from runner.api import RunRequest, run

ROOT = Path(__file__).resolve().parents[1]


def _command() -> str:
    return f'"{sys.executable}" "{ROOT / "tests/scenario_agent.py"}"'


def _records(state_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (state_dir / "prompt-log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]


@pytest.mark.parametrize("backend", ["qwen", "opencode"])
def test_happy_path_uses_bounded_stage_specific_prompts(tmp_path, monkeypatch, backend):
    state_dir = tmp_path.parent / f"{tmp_path.name}-mock-state"
    monkeypatch.setenv("SCENARIO", "happy_path")
    monkeypatch.setenv("SCENARIO_STATE_DIR", str(state_dir))
    noise_names = [f"unrelated-{index:03d}.txt" for index in range(40)]
    for name in noise_names:
        (tmp_path / name).write_text("unrelated", encoding="utf-8")

    result = run(RunRequest(
        goal="Create the requested result",
        project_root=str(tmp_path),
        validator="ai",
        backend=backend,
        command=_command(),
        max_attempts=3,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
    ))

    assert result.completed is True
    records = _records(state_dir)
    assert [record["stage"] for record in records] == [
        "plan_finalize",
        "execute",
        "review",
        "validator",
    ]
    assert [record["resumed"] for record in records] == [
        False,
        True,
        False,
        False,
    ]

    limits = {
        "plan_finalize": 5000,
        "execute": 4500,
        "review": 4500,
        "validator": 7000,
    }
    assert all(record["chars"] <= limits[record["stage"]] for record in records)

    prompts = "\n".join(record["prompt"] for record in records)
    assert not any(name in prompts for name in noise_names)
    assert {
        record["stage"]
        for record in records
        if str(tmp_path) in record["prompt"]
    } == {"plan_finalize", "execute", "validator"}
    assert len({record["prompt"] for record in records}) == len(records)


def test_recovery_scenarios_add_only_explainable_model_calls(tmp_path, monkeypatch):
    expectations = {
        "review_retry": {
            "plan_finalize": 1,
            "execute": 2,
            "review": 2,
            "validator": 1,
        },
        "execution_model_error": {
            "plan_finalize": 1,
            "execute": 4,
            "review": 1,
            "validator": 1,
        },
        "ai_replan": {
            "plan_finalize": 2,
            "execute": 2,
            "review": 2,
            "validator": 2,
        },
    }

    for scenario, expected in expectations.items():
        project = tmp_path / scenario
        project.mkdir()
        state_dir = tmp_path / f"{scenario}-state"
        monkeypatch.setenv("SCENARIO", scenario)
        monkeypatch.setenv("SCENARIO_STATE_DIR", str(state_dir))

        result = run(RunRequest(
            goal="Create the requested result",
            project_root=str(project),
            validator="ai",
            backend="qwen",
            command=_command(),
            max_attempts=6,
            max_cycles=3,
            retry_delay=0,
            retry_wait=0,
            retry_max_wait=0,
        ))

        assert result.completed is True, scenario
        records = _records(state_dir)
        assert Counter(record["stage"] for record in records) == expected
        assert all(record["stage"] != "unknown" for record in records)



@pytest.mark.parametrize("scenario", ["execution_model_error", "review_retry", "api_503"])
def test_opencode_recovery_uses_same_runner_contract(tmp_path, monkeypatch, scenario):
    state_dir = tmp_path.parent / f"{tmp_path.name}-{scenario}-opencode-state"
    monkeypatch.setenv("SCENARIO", scenario)
    monkeypatch.setenv("SCENARIO_STATE_DIR", str(state_dir))

    result = run(RunRequest(
        goal=f"Create the requested result for OpenCode {scenario}",
        project_root=str(tmp_path),
        validator="ai",
        backend="opencode",
        command=_command(),
        max_attempts=3,
        max_cycles=3,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
        api_wait_timeout=10,
    ))

    assert result.completed is True
    records = _records(state_dir)
    assert all(record["stage"] != "unknown" for record in records)
    assert any(record["resumed"] for record in records if record["stage"] == "execute")

def test_generic_workflow_and_prompts_have_no_backend_or_example_literals():
    generic_paths = [
        ROOT / "runner" / "task_runner.py",
        *(ROOT / "runner" / "agent").rglob("*.py"),
        *(ROOT / "runner" / "agent" / "prompt_templates").glob("*.md"),
        *(ROOT / "runner" / "workflow").rglob("*.py"),
        *(ROOT / "runner" / "safety").rglob("*.py"),
    ]
    forbidden = ("qwen", "opencode", "examples/", "examples\\")

    offenders = {
        str(path.relative_to(ROOT)): term
        for path in generic_paths
        for term in forbidden
        if term in path.read_text(encoding="utf-8").lower()
    }

    assert offenders == {}


def _file_validator(path: Path) -> None:
    path.write_text(
        "from pathlib import Path\n"
        "import argparse\n"
        "p=argparse.ArgumentParser(); p.add_argument('--project-root'); p.add_argument('--state-file'); a,_=p.parse_known_args()\n"
        "raise SystemExit(0 if (Path(a.project_root)/'done.txt').exists() else 5)\n",
        encoding="utf-8",
    )



@pytest.mark.parametrize("scenario", ["execution_model_error", "review_retry", "api_503"])
@pytest.mark.parametrize("mode", ["ai", "python", "mixed"])
def test_recovery_scenarios_cross_ai_python_and_mixed_validation(
    tmp_path, monkeypatch, scenario, mode
):
    state_dir = tmp_path.parent / f"{tmp_path.name}-{scenario}-{mode}-state"
    monkeypatch.setenv("SCENARIO", scenario)
    monkeypatch.setenv("SCENARIO_STATE_DIR", str(state_dir))
    validator = "ai"
    ai_validator_prompt = ""
    if mode != "ai":
        validator_path = tmp_path / "validator.py"
        _file_validator(validator_path)
        validator = str(validator_path)
        if mode == "mixed":
            ai_validator_prompt = "Independently confirm done.txt exists."

    result = run(RunRequest(
        goal=f"Create requested result for {scenario} {mode}",
        project_root=str(tmp_path),
        validator=validator,
        ai_validator_prompt=ai_validator_prompt,
        backend="qwen",
        command=_command(),
        max_attempts=2,
        max_cycles=3,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
        api_wait_timeout=10,
        agent_idle_after_change_timeout=0,
        final_ai_validations=1,
        final_ai_required_passes=1,
    ))

    assert result.completed is True
    records = _records(state_dir)
    assert any(record["stage"] == "execute" for record in records)
    if mode == "ai":
        assert any(record["stage"] == "validator" for record in records)
    elif mode == "python":
        assert all(record["stage"] != "validator" for record in records)
    else:
        assert any(record["stage"] == "validator" for record in records)


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

    result = run(RunRequest(
        goal="Create first.txt then second.txt",
        project_root=str(tmp_path),
        validator=str(validator),
        backend="qwen",
        command=_command(),
        max_attempts=2,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
    ))

    assert result.completed is True
    execute = [record for record in _records(state_dir) if record["stage"] == "execute"]
    assert len(execute) == 2
    assert execute[0]["resumed"] is True
    assert "Goal (context/global constraints only):" in execute[0]["prompt"]
    assert execute[1]["resumed"] is True
    assert execute[1]["prompt"].startswith("Continue normal task execution in this same session.")
    assert '"title": "Create second marker"' in execute[1]["prompt"]
    assert "Goal (context/global constraints only):" not in execute[1]["prompt"]
    assert "Hard rules:" not in execute[1]["prompt"]
    assert execute[1]["chars"] < execute[0]["chars"] // 2


def test_review_repair_same_session_sends_only_new_evidence(tmp_path, monkeypatch):
    state_dir = tmp_path.parent / f"{tmp_path.name}-review-context-state"
    monkeypatch.setenv("SCENARIO", "review_retry")
    monkeypatch.setenv("SCENARIO_STATE_DIR", str(state_dir))

    result = run(RunRequest(
        goal="Create the requested result",
        project_root=str(tmp_path),
        validator="ai",
        backend="qwen",
        command=_command(),
        max_attempts=2,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
        final_ai_validations=1,
        final_ai_required_passes=1,
    ))

    assert result.completed is True
    records = _records(state_dir)
    reviews = [record for record in records if record["stage"] == "review"]
    executes = [record for record in records if record["stage"] == "execute"]
    assert len(reviews) == 2
    assert reviews[1]["resumed"] is True
    assert reviews[1]["prompt"].startswith(
        "Continue reviewing the same current TODO in this same review session."
    )
    assert "Evidence order:" not in reviews[1]["prompt"]
    assert "Decision:" not in reviews[1]["prompt"]
    assert any(
        record["prompt"].startswith("Continue normal task execution in this same session.")
        and "Latest review:" in record["prompt"]
        for record in executes
    )
