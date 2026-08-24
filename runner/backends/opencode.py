"""OpenCode CLI backend."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..model.backend import ModelBackend, BackendResult, ensure_project_rules


class OpenCodeBackend(ModelBackend):
    name = "opencode"
    default_command = "opencode"

    def build_command(self, prompt: str, session_id: str) -> list[str]:
        session_args = ["--session", session_id] if session_id else []
        return [
            *self.base_command,
            "run",
            "--dir",
            str(self.root),
            "--format",
            "json",
            *session_args,
            *self.extra_args,
        ]

    def decode(self, raw: str) -> BackendResult:
        values = self.parse_json_events(raw)
        if not values:
            return BackendResult(raw)

        session_id = self.find_session_id(values)
        text = self._find_last_text(values)
        return BackendResult(text if text is not None else raw, session_id)

    def prepare_project(self) -> list[Path]:
        return [ensure_opencode_rules(self.root)]

    @staticmethod
    def _find_last_text(values: Sequence[Any]) -> str | None:
        texts: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if isinstance(value.get("text"), str):
                    texts.append(value["text"])
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        for value in values:
            visit(value)
        return texts[-1] if texts else None


def ensure_opencode_rules(root: Path) -> Path:
    """Create or extend the OpenCode project rule file."""
    return ensure_project_rules(root, "AGENTS.md")
