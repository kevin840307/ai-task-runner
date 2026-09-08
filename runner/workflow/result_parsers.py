"""Structured response parsers for bundled workflow stages."""
from __future__ import annotations

from typing import Any

from ..ai.structured_output import AIValidationResult, ReviewResult, parse_result, require_object, require_text, require_text_list
from ..errors import RunnerError
from .stages.contracts import StageContext

MAX_MISSING_ITEMS = 100
MAX_MISSING_ITEM_CHARS = 1_000
MAX_REASON_CHARS = 4_000


def _decision(value: Any, *, flag: str, prefix: str) -> tuple[bool, str, list[str]]:
    value = require_object(value)
    verdict = value.get(flag)
    if not isinstance(verdict, bool):
        raise RunnerError(f"{prefix}.{flag} must be boolean")
    missing = [
        item[:MAX_MISSING_ITEM_CHARS]
        for item in require_text_list(value.get("missing_items", []), f"{prefix}.missing_items")[:MAX_MISSING_ITEMS]
    ]
    if verdict == bool(missing):
        state = "passed/completed" if verdict else "failed"
        expected = "empty" if verdict else "non-empty"
        raise RunnerError(f"{state} {prefix} must have {expected} missing_items")
    reason = require_text(value.get("reason"), f"{prefix}.reason")[:MAX_REASON_CHARS]
    return verdict, reason, missing


def parse_review(text: str, ctx: StageContext) -> ReviewResult:
    def parse(value: Any) -> ReviewResult:
        completed, reason, missing = _decision(value, flag="completed", prefix="review")
        return {"completed": completed, "reason": reason, "missing_items": missing}
    return parse_result(text, parse)


def parse_ai_validation(text: str, ctx: StageContext | None = None) -> AIValidationResult:
    def parse(value: Any) -> AIValidationResult:
        obj = require_object(value)
        passed, reason, missing = _decision(obj, flag="passed", prefix="validator")
        return {
            "passed": passed,
            "reason": reason,
            "missing_items": missing,
            "checks_run": require_text_list(obj.get("checks_run", []), "validator.checks_run")[:MAX_MISSING_ITEMS],
            "suggested_checks": require_text_list(obj.get("suggested_checks", []), "validator.suggested_checks")[:MAX_MISSING_ITEMS],
        }
    return parse_result(text, parse)


PARSERS = {
    "review": parse_review,
    "validation": parse_ai_validation,
}

__all__ = ["PARSERS", "parse_review", "parse_ai_validation"]
