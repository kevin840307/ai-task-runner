"""Qwen CLI backend."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .base import AgentBackend, BackendResult


class QwenBackend(AgentBackend):
    name = "qwen"
    default_command = "qwen"

    def build_command(self, prompt: str, session_id: str) -> list[str]:
        session_args = ["--resume", session_id] if session_id else []
        return [
            *self.base_command,
            *session_args,
            "-p",
            prompt,
            "--output-format",
            "json",
            *self.extra_args,
        ]

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
    path = root / ".qwen" / "QWEN.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    marker = "# AI Task Runner Rules"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker not in existing:
        block = f"""

{marker}
- You may read files outside this project when needed.
- You may write, create, rename, or delete files only under: {root}
- Never modify validator files, runner state, or this rule file.
- Python owns task order and completion state.
- Execute only the current task supplied by the runner.
- Never ask the user questions. Inspect the project, make the safest reasonable assumption, and continue.
"""
        path.write_text(existing.rstrip() + block, encoding="utf-8")
    return path
