"""Qwen CLI backend."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .base import AgentBackend, BackendResult, ensure_project_rules


class QwenBackend(AgentBackend):
    name = "qwen"
    default_command = "qwen"

    def build_command(self, prompt: str, session_id: str) -> list[str]:
        session_args = ["--resume", session_id] if session_id else []
        return [
            *self.base_command,
            *session_args,
            "-p",
            single_line_prompt(prompt),
            "--output-format",
            "json",
            *self.extra_args,
        ]

    def prompt_stdin(self, prompt: str) -> str:
        return prompt

    def decode(self, raw: str) -> BackendResult:
        values = self.parse_json_events(raw)
        if not values:
            return BackendResult(raw)

        session_id = self.find_session_id(values)
        result = self._find_result(values)
        return BackendResult(result if result is not None else raw, session_id)

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


def ensure_qwen_rules(root: Path) -> Path:
    """Create or extend the Qwen project rule file."""
    return ensure_project_rules(root, "QWEN.md")


def single_line_prompt(prompt: str) -> str:
    """Avoid qwen.cmd on Windows receiving only the first prompt line."""
    return " ".join(line.strip() for line in prompt.splitlines() if line.strip())
