import json

import pytest

from runner.errors import RunnerError
from runner.model_results import (
    parse_ai_validation,
    parse_plan_judgment,
    parse_review,
    parse_tasks,
)


def task(title="A"):
    return {
        "title": title,
        "description": "Implement one bounded change",
        "deliverable": "changed file",
        "acceptance_criteria": ["change is correct"],
    }


def test_tasks_accept_fenced_json_with_surrounding_text():
    raw = "before\n```json\n" + json.dumps({"tasks": [task(str(i)) for i in range(6)]}) + "\n```\nafter"
    assert len(parse_tasks(raw, 1, min_tasks=6, require_deliverable=True)) == 6


def test_tasks_skip_unrelated_json_and_use_matching_candidate():
    raw = json.dumps({"status": "planning"}) + "\nnotes\n" + json.dumps({"tasks": [task(str(i)) for i in range(6)]})
    assert len(parse_tasks(raw, 1, min_tasks=6, require_deliverable=True)) == 6


def test_tasks_do_not_treat_nested_object_as_separate_candidate():
    raw = json.dumps({"wrapper": {"tasks": [task(str(i)) for i in range(6)]}})
    with pytest.raises(RunnerError, match="tasks must contain at least 6 items"):
        parse_tasks(raw, 1, min_tasks=6, require_deliverable=True)


def test_broken_json_is_not_repaired():
    raw = '{"tasks": ['
    with pytest.raises(RunnerError, match="malformed or incomplete JSON"):
        parse_tasks(raw, 1, min_tasks=6, require_deliverable=True)


def test_valid_json_with_invalid_task_schema_stays_invalid():
    raw = json.dumps({"tasks": ["a"] * 6})
    with pytest.raises(RunnerError, match=r"tasks\[1\] must be an object"):
        parse_tasks(raw, 1, min_tasks=6, require_deliverable=True)


def test_judge_review_and_validator_share_candidate_selection():
    prefix = json.dumps({"status": "done"}) + "\n"
    assert parse_plan_judgment(prefix + json.dumps({"accepted": True, "issues": []}))["accepted"] is True
    assert parse_review(prefix + json.dumps({"completed": True, "reason": "ok", "missing_items": []}))["completed"] is True
    assert parse_ai_validation(prefix + json.dumps({"passed": True, "reason": "ok", "missing_items": [], "checks_run": [], "suggested_checks": []}))["passed"] is True


def test_incomplete_outer_tasks_json_reports_json_error_not_nested_schema_error():
    raw = '{"tasks": [{"title":"A","description":"x","deliverable":"y","acceptance_criteria":["z"]}'
    with pytest.raises(RunnerError, match="malformed or incomplete JSON"):
        parse_tasks(raw, 1)
