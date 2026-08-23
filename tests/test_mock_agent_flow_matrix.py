from __future__ import annotations

import json
import sys
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


def test_happy_path_uses_bounded_stage_specific_prompts(tmp_path, monkeypatch):
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
        backend="qwen",
        command=_command(),
        max_attempts=3,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
    ))

    assert result.completed is True
    records = _records(state_dir)
    assert [record["stage"] for record in records] == [
        "plan_understand",
        "plan_finalize",
        "plan_judge",
        "execute",
        "review",
        "validator",
    ]
    assert [record["resumed"] for record in records] == [
        False,
        True,
        True,
        True,
        False,
        False,
    ]

    limits = {
        "plan_understand": 6000,
        "plan_finalize": 4000,
        "plan_judge": 3000,
        "execute": 2500,
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
    } == {"plan_understand", "validator"}
    assert len({record["prompt"] for record in records}) == len(records)


def test_recovery_scenarios_add_only_explainable_model_calls(tmp_path, monkeypatch):
    expectations = {
        "review_retry": {
            "plan_understand": 1,
            "plan_finalize": 1,
            "plan_judge": 1,
            "execute": 2,
            "review": 2,
            "validator": 1,
        },
        "execution_model_error": {
            "plan_understand": 1,
            "plan_finalize": 1,
            "plan_judge": 1,
            "execute": 4,
            "review": 1,
            "validator": 1,
        },
        "ai_replan": {
            "plan_understand": 2,
            "plan_finalize": 2,
            "plan_judge": 2,
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


def test_generic_workflow_and_prompts_have_no_backend_or_example_literals():
    generic_paths = [
        ROOT / "runner" / "engine" / "core.py",
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
