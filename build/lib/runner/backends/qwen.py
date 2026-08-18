"""Qwen CLI backend."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from runner.defaults import DEFAULT_QWEN_COMMAND
from .base import AgentBackend, BackendError, BackendResult, ensure_project_rules


class QwenBackend(AgentBackend):
    name = "qwen"
    default_command = DEFAULT_QWEN_COMMAND

    def build_command(self, prompt: str, session_id: str) -> list[str]:
        if not prompt.strip():
            raise BackendError("qwen prompt is empty")
        session_args = ["--resume", session_id] if session_id else []
        return [
            *self.base_command,
            *session_args,
            "--output-format",
            "stream-json",
            *self.extra_args,
        ]

    def stdin_prompt(self, prompt: str) -> str:
        return prompt

    def decode(self, raw: str) -> BackendResult:
        values = self.parse_json_events(raw)
        if not values:
            return BackendResult(raw)

        session_id = self.find_session_id(values)
        result = self._find_result(values)
        return BackendResult(result if result is not None else raw, session_id)

    def error_output(self, raw: str) -> str:
        values = self.parse_json_events(raw)
        if not values:
            return raw
        return (
            self._find_error_message(values)
            or self._find_result(values)
            or self._find_assistant_text(values)
            or raw
        )

    def prepare_project(self) -> list[Path]:
        return [ensure_qwen_rules(self.root)]

    @staticmethod
    def _find_result(values: Sequence[Any]) -> str | None:
        for value in reversed(values):
            items = value if isinstance(value, list) else [value]
            for item in reversed(items):
                if isinstance(item, dict) and isinstance(item.get("result"), str):
                    return item["result"]
        return None

    @staticmethod
    def _find_error_message(values: Sequence[Any]) -> str | None:
        for value in reversed(values):
            items = value if isinstance(value, list) else [value]
            for item in reversed(items):
                if not isinstance(item, dict):
                    continue
                error = item.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    return error["message"]
                if isinstance(item.get("error"), str):
                    return item["error"]
        return None

    @staticmethod
    def _find_assistant_text(values: Sequence[Any]) -> str | None:
        for value in reversed(values):
            items = value if isinstance(value, list) else [value]
            for item in reversed(items):
                if not isinstance(item, dict):
                    continue
                message = item.get("message")
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    ]
                    text = "\n".join(part for part in parts if part)
                    if text:
                        return text
        return None


def ensure_qwen_rules(root: Path) -> Path:
    """Create or extend the Qwen project rule file."""
    return ensure_project_rules(root, "QWEN.md")



GOAL_REFERENCE_START = "<!-- AI-TASK-RUNNER:GOAL-REFERENCE -->"
GOAL_REFERENCE_END = "<!-- /AI-TASK-RUNNER:GOAL-REFERENCE -->"


def update_qwen_goal_reference(root: Path, goal_file: str | None) -> Path:
    """Maintain a replaceable goal-file reference in the project QWEN.md."""
    path = ensure_qwen_rules(root)
    text = path.read_text(encoding="utf-8")
    start = text.find(GOAL_REFERENCE_START)
    if start >= 0:
        end = text.find(GOAL_REFERENCE_END, start)
        if end >= 0:
            text = (text[:start] + text[end + len(GOAL_REFERENCE_END):]).rstrip()
    if goal_file:
        reference = Path(goal_file).expanduser().resolve().as_posix()
        text += f"""

{GOAL_REFERENCE_START}
Original requirement file: {reference}

If the original requirements are unclear, missing from context, or appear to
conflict with the current task or feedback, reread this file before continuing.
The original requirements remain authoritative; review or validator feedback
does not replace or narrow them.
{GOAL_REFERENCE_END}
"""
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path
