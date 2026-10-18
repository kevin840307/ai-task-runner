"""Normalized Project Chat Ask / clarification schema.

This module owns only the transport model for interactive questions. Persistence
belongs to ChatService; Agent-specific question transport belongs to adapters.
"""
from __future__ import annotations

from typing import Any

MAX_QUESTIONS = 12
MAX_OPTIONS = 4
MAX_HEADER = 80
MAX_PROMPT = 1200
MAX_OPTION_TEXT = 240
MAX_ANSWER_TEXT = 4000


def _text(value: Any, label: str, limit: int, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{label} is required")
    if len(text) > limit:
        raise ValueError(f"{label} is too long")
    return text


def normalize_questions(raw: Any) -> list[dict[str, Any]]:
    """Return the one canonical Ask question shape used by API and UI."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("Ask questions must be a non-empty list")
    if len(raw) > MAX_QUESTIONS:
        raise ValueError(f"Ask supports at most {MAX_QUESTIONS} questions")

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(raw):
        if not isinstance(value, dict):
            raise ValueError("Ask question must be an object")
        question_id = _text(
            value.get("question_id") or value.get("id") or f"q{index + 1}",
            "Ask question id",
            80,
        )
        if question_id in seen:
            raise ValueError("Ask question ids must be unique")
        seen.add(question_id)

        prompt = _text(
            value.get("prompt") or value.get("question"),
            "Ask question",
            MAX_PROMPT,
        )
        header = _text(
            value.get("header") or f"Question {index + 1}",
            "Ask header",
            MAX_HEADER,
        )
        raw_options = value.get("options")
        kind = str(value.get("kind") or ("choice" if raw_options else "text")).strip().lower()
        if kind not in {"choice", "text"}:
            raise ValueError("Ask question kind must be choice or text")

        options: list[dict[str, str]] = []
        option_seen: set[str] = set()
        if kind == "choice":
            if not isinstance(raw_options, list) or not raw_options:
                raise ValueError("Choice Ask question requires options")
            if len(raw_options) > MAX_OPTIONS:
                raise ValueError(
                    f"Choice Ask question supports at most {MAX_OPTIONS} options plus Other"
                )
            for option in raw_options:
                if isinstance(option, dict):
                    option_value = _text(
                        option.get("value") or option.get("label"),
                        "Ask option value",
                        MAX_OPTION_TEXT,
                    )
                    label = _text(
                        option.get("label") or option_value,
                        "Ask option label",
                        MAX_OPTION_TEXT,
                    )
                    description = _text(
                        option.get("description"),
                        "Ask option description",
                        MAX_OPTION_TEXT,
                        required=False,
                    )
                else:
                    option_value = _text(option, "Ask option value", MAX_OPTION_TEXT)
                    label = option_value
                    description = ""
                if option_value in option_seen:
                    raise ValueError("Ask option values must be unique")
                option_seen.add(option_value)
                options.append({
                    "value": option_value,
                    "label": label,
                    "description": description,
                })
        elif raw_options not in (None, [], ()):
            raise ValueError("Text Ask question cannot define options")

        result.append({
            "question_id": question_id,
            "header": header,
            "prompt": prompt,
            "kind": kind,
            "options": options,
            "allow_other": kind == "choice",
        })
    return result


def validate_answers(
    questions: list[dict[str, Any]],
    raw: Any,
) -> dict[str, Any]:
    """Validate and canonicalize a complete answer set for one Ask."""
    if not isinstance(raw, dict):
        raise ValueError("Ask answers must be an object")
    expected = {item["question_id"] for item in questions}
    unknown = set(str(key) for key in raw) - expected
    if unknown:
        raise ValueError(f"Unknown Ask answer: {sorted(unknown)[0]}")

    result: dict[str, Any] = {}
    for question in questions:
        question_id = question["question_id"]
        if question_id not in raw:
            raise ValueError(f"Ask answer is required: {question_id}")
        answer = raw[question_id]
        if question["kind"] == "text":
            result[question_id] = _text(
                answer,
                "Ask text answer",
                MAX_ANSWER_TEXT,
            )
            continue

        values = {item["value"] for item in question["options"]}
        if isinstance(answer, dict) and "other" in answer:
            custom = _text(answer.get("other"), "Ask custom answer", MAX_ANSWER_TEXT)
            result[question_id] = {"other": custom}
            continue
        selected = answer.get("value") if isinstance(answer, dict) else answer
        selected_text = _text(selected, "Ask choice answer", MAX_OPTION_TEXT)
        if selected_text not in values:
            raise ValueError(f"Invalid Ask option for {question_id}")
        result[question_id] = {"value": selected_text}
    return result
