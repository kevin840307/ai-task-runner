"""AI response parsing and structured-output contracts."""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any, TypedDict, TypeVar

from ..errors import RunnerError, StructuredOutputError
from ..prompts.loader import structured_retry_prompt

T = TypeVar("T")



class _ReviewResultRequired(TypedDict):
    completed: bool
    reason: str
    missing_items: list[str]


class ReviewResult(_ReviewResultRequired, total=False):
    review_skipped: bool


class AIValidationResult(TypedDict):
    passed: bool
    reason: str
    missing_items: list[str]
    checks_run: list[str]
    suggested_checks: list[str]


def json_candidates(text: str) -> Iterator[Any]:
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


def parse_result(text: str, parser: Callable[[Any], T]) -> T:
    errors: list[RunnerError] = []
    found = False
    for value in json_candidates(text):
        found = True
        try:
            return parser(value)
        except RunnerError as error:
            errors.append(error)
    if errors:
        raise errors[-1]
    if found:
        raise RunnerError("model response has no accepted structured result")
    raise RunnerError("model response has no valid JSON result")


def require_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RunnerError("model JSON result must be an object")
    return value


def require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunnerError(f"{field} must be a non-empty string")
    return value.strip()


def require_text_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list):
        raise RunnerError(f"{field} must be an array of strings")
    result = [require_text(item, f"{field}[{index}]") for index, item in enumerate(value, 1)]
    if not allow_empty and not result:
        raise RunnerError(f"{field} must not be empty")
    return result




def structured_call(
    prompt: str, parser: Callable[[str], T], ask: Callable[[str], str], *,
    retries: int = 1, retry_prompt: Callable[[str], str] = structured_retry_prompt,
    fresh_ask: Callable[[], str] | None = None, fresh_retries: int = 0,
) -> T:
    raw = ask(prompt)
    fresh_round = 0
    while True:
        for attempt in range(retries + 1):
            try:
                return parser(raw)
            except RunnerError as error:
                if attempt < retries:
                    raw = ask(retry_prompt(str(error)))
                    continue
                if fresh_ask is None or fresh_round >= fresh_retries:
                    exhausted = StructuredOutputError(str(error))
                    if fresh_retries:
                        exhausted.same_session_retry_limit = 0
                    raise exhausted from error
                fresh_round += 1
                raw = fresh_ask()
                break


__all__ = [
    "ReviewResult", "AIValidationResult", "json_candidates", "parse_result",
    "require_object", "require_text", "require_text_list", "structured_call",
]
