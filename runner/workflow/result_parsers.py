"""Structured response parsers for bundled workflow stages."""
from __future__ import annotations

from typing import Any

from ..ai.structured_output import AIValidationResult, ReviewResult, parse_result, require_object, require_text, require_text_list
from ..errors import RunnerError
from .stages.contracts import StageContext

MAX_MISSING_ITEMS = 100
MAX_MISSING_ITEM_CHARS = 1_000
MAX_REASON_CHARS = 4_000


def parse_review(text: str, ctx: StageContext) -> ReviewResult:
    def parse(value: Any) -> ReviewResult:
        value = require_object(value)
        if not isinstance(value.get("completed"), bool):
            raise RunnerError("review.completed must be boolean")
        missing = [item[:MAX_MISSING_ITEM_CHARS] for item in require_text_list(value.get("missing_items", []), "review.missing_items")[:MAX_MISSING_ITEMS]]
        if value["completed"] and missing:
            raise RunnerError("completed review must have empty missing_items")
        if not value["completed"] and not missing:
            raise RunnerError("failed review must have non-empty missing_items")
        return {
            "completed": value["completed"],
            "reason": require_text(value.get("reason"), "review.reason")[:MAX_REASON_CHARS],
            "missing_items": missing,
        }
    return parse_result(text, parse)


def parse_ai_validation(text: str, ctx: StageContext | None = None) -> AIValidationResult:
    def parse(value: Any) -> AIValidationResult:
        value = require_object(value)
        if not isinstance(value.get("passed"), bool):
            raise RunnerError("validator.passed must be boolean")
        return {
            "passed": value["passed"],
            "reason": require_text(value.get("reason"), "validator.reason")[:MAX_REASON_CHARS],
            "missing_items": [item[:MAX_MISSING_ITEM_CHARS] for item in require_text_list(value.get("missing_items", []), "validator.missing_items")[:MAX_MISSING_ITEMS]],
            "checks_run": require_text_list(value.get("checks_run", []), "validator.checks_run")[:MAX_MISSING_ITEMS],
            "suggested_checks": require_text_list(value.get("suggested_checks", []), "validator.suggested_checks")[:MAX_MISSING_ITEMS],
        }
    return parse_result(text, parse)


PARSERS = {
    "review": parse_review,
    "validation": parse_ai_validation,
}

__all__ = ["PARSERS", "parse_review", "parse_ai_validation"]
