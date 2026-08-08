"""Strict parsers for structured model planning, review, and validation results."""
from __future__ import annotations

import json
import re
from typing import Any

from .errors import RunnerError
from .models import Task


MAX_RESULT_REASON_CHARS = 4_000
MAX_MISSING_ITEMS = 100
MAX_MISSING_ITEM_CHARS = 1_000


def parse_json(text: str) -> dict[str, Any]:
    """Extract the first valid JSON object from plain or fenced model output."""
    candidates = [
        text.strip(),
        *re.findall(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            text,
            re.DOTALL | re.IGNORECASE,
        ),
    ]
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    start = text.find("{")
    while start >= 0:
        candidate = _balanced_json_object(text, start)
        if candidate is not None:
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(value, dict):
                    return value
        start = text.find("{", start + 1)
    raise RunnerError("AI response has no valid JSON object")


def _balanced_json_object(text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunnerError(f"{field_name} must be a non-empty string")
    return value.strip()


def require_string_list(
    value: Any,
    field_name: str,
    allow_empty: bool = True,
) -> list[str]:
    if not isinstance(value, list):
        raise RunnerError(f"{field_name} must be an array of strings")
    result = [
        require_non_empty_string(item, f"{field_name}[{index}]")
        for index, item in enumerate(value, 1)
    ]
    if not allow_empty and not result:
        raise RunnerError(f"{field_name} must not be empty")
    return result


def parse_tasks(
    text: str,
    cycle: int,
    *,
    min_tasks: int = 1,
    require_deliverable: bool = False,
) -> list[Task]:
    raw_tasks = parse_json(text).get("tasks")
    if not isinstance(raw_tasks, list) or len(raw_tasks) < min_tasks:
        raise RunnerError(f"tasks must contain at least {min_tasks} items")

    tasks: list[Task] = []
    for index, item in enumerate(raw_tasks, 1):
        if not isinstance(item, dict):
            raise RunnerError(f"tasks[{index}] must be an object")
        title = require_non_empty_string(item.get("title"), f"tasks[{index}].title")
        description = require_non_empty_string(
            item.get("description"), f"tasks[{index}].description"
        )
        deliverable = item.get("deliverable", "")
        if require_deliverable:
            deliverable = require_non_empty_string(
                deliverable, f"tasks[{index}].deliverable"
            )
        elif deliverable:
            deliverable = require_non_empty_string(
                deliverable, f"tasks[{index}].deliverable"
            )
        criteria_value = item.get("acceptance_criteria", item.get("accept_criteria"))
        criteria = require_string_list(
            criteria_value,
            f"tasks[{index}].acceptance_criteria",
            allow_empty=False,
        )
        tasks.append(
            Task(
                id=f"c{cycle:02d}-t{index:03d}",
                title=title,
                description=description,
                acceptance_criteria=criteria,
                deliverable=deliverable,
            )
        )
    return tasks


def parse_plan_judgment(text: str, task_count: int) -> dict[str, Any]:
    del task_count  # Kept for public-call compatibility.
    value = parse_json(text)
    if not isinstance(value.get("accepted"), bool):
        raise RunnerError("plan_judge.accepted must be boolean")
    issues = require_string_list(value.get("issues", []), "plan_judge.issues")
    accepted = value["accepted"] and not issues
    if not accepted and not issues:
        issues = ["The plan did not pass the quality judge"]
    return {
        "accepted": accepted,
        "issues": [
            item[:MAX_MISSING_ITEM_CHARS]
            for item in issues[:MAX_MISSING_ITEMS]
        ],
    }


def _bounded_result_text(value: Any, field_name: str) -> str:
    return require_non_empty_string(value, field_name)[:MAX_RESULT_REASON_CHARS]


def _bounded_missing_items(value: Any, field_name: str) -> list[str]:
    items = require_string_list(value, field_name)[:MAX_MISSING_ITEMS]
    return [item[:MAX_MISSING_ITEM_CHARS] for item in items]


def parse_review(text: str) -> dict[str, Any]:
    value = parse_json(text)
    if not isinstance(value.get("completed"), bool):
        raise RunnerError("review.completed must be boolean")
    missing_items = _bounded_missing_items(
        value.get("missing_items", []),
        "review.missing_items",
    )
    if value["completed"] and missing_items:
        raise RunnerError("completed review must have empty missing_items")
    if not value["completed"] and not missing_items:
        raise RunnerError("failed review must have non-empty missing_items")
    return {
        "completed": value["completed"],
        "reason": _bounded_result_text(value.get("reason"), "review.reason"),
        "missing_items": missing_items,
    }


def parse_ai_validation(text: str) -> dict[str, Any]:
    value = parse_json(text)
    if not isinstance(value.get("passed"), bool):
        raise RunnerError("validator.passed must be boolean")
    return {
        "passed": value["passed"],
        "reason": _bounded_result_text(
            value.get("reason"),
            "validator.reason",
        ),
        "missing_items": _bounded_missing_items(
            value.get("missing_items", []),
            "validator.missing_items",
        ),
        "checks_run": _bounded_missing_items(
            value.get("checks_run", []),
            "validator.checks_run",
        ),
        "suggested_checks": _bounded_missing_items(
            value.get("suggested_checks", []),
            "validator.suggested_checks",
        ),
    }


__all__ = [
    "MAX_MISSING_ITEM_CHARS",
    "MAX_MISSING_ITEMS",
    "MAX_RESULT_REASON_CHARS",
    "parse_ai_validation",
    "parse_json",
    "parse_plan_judgment",
    "parse_review",
    "parse_tasks",
    "require_non_empty_string",
    "require_string_list",
]
