"""Strict parsers for structured model planning, review, and validation results."""
from __future__ import annotations

import json
from typing import Any, Callable, Iterator, TypeVar

from ..errors import RunnerError
from ..models import AIValidationResult, PlanJudgment, ReviewResult, Task


MAX_RESULT_REASON_CHARS = 4_000
MAX_MISSING_ITEMS = 100
MAX_MISSING_ITEM_CHARS = 1_000
T = TypeVar("T")


def _json_candidates(text: str) -> Iterator[Any]:
    """Yield valid JSON values embedded in model output without repairing them."""
    text = text.strip().lstrip("\ufeff")
    if not text:
        return
    decoder = json.JSONDecoder()
    try:
        yield json.loads(text)
        return
    except json.JSONDecodeError:
        pass

    index = 0
    while index < len(text):
        if text[index] not in "{[":
            index += 1
            continue
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index += 1
            continue
        yield value
        index = end


def _parse_result(text: str, parser: Callable[[Any], T]) -> T:
    """Return the first JSON candidate accepted by one stage-specific parser."""
    errors = []
    found = False
    for value in _json_candidates(text):
        found = True
        try:
            return parser(value)
        except RunnerError as error:
            errors.append(error)

    stripped = text.strip().lstrip("\ufeff")
    opener = min(
        (index for index in (stripped.find("{"), stripped.find("[")) if index >= 0),
        default=-1,
    )
    if opener >= 0:
        try:
            json.JSONDecoder().raw_decode(stripped, opener)
        except json.JSONDecodeError as error:
            raise RunnerError(
                f"AI response contains malformed or incomplete JSON at "
                f"line {error.lineno}, column {error.colno}: {error.msg}"
            ) from error

    if errors:
        raise errors[-1]
    if found:
        raise RunnerError("AI response has no valid structured JSON result")
    raise RunnerError("AI response has no valid JSON object")


def _require_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RunnerError("AI JSON result must be an object")
    return value


def parse_json(text: str) -> dict[str, Any]:
    """Compatibility API: return the first valid JSON object in model output."""
    return _parse_result(text, _require_object)


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
    def parse(value: Any) -> list[Task]:
        raw_tasks = _require_object(value).get("tasks")
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

    return _parse_result(text, parse)


def parse_plan_judgment(text: str) -> PlanJudgment:
    def parse(value: Any) -> PlanJudgment:
        value = _require_object(value)
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

    return _parse_result(text, parse)


def _bounded_result_text(value: Any, field_name: str) -> str:
    return require_non_empty_string(value, field_name)[:MAX_RESULT_REASON_CHARS]


def _bounded_missing_items(value: Any, field_name: str) -> list[str]:
    items = require_string_list(value, field_name)[:MAX_MISSING_ITEMS]
    return [item[:MAX_MISSING_ITEM_CHARS] for item in items]


def parse_review(text: str) -> ReviewResult:
    def parse(value: Any) -> ReviewResult:
        value = _require_object(value)
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

    return _parse_result(text, parse)


def parse_ai_validation(text: str) -> AIValidationResult:
    def parse(value: Any) -> AIValidationResult:
        value = _require_object(value)
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

    return _parse_result(text, parse)


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
