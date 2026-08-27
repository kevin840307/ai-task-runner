"""OpenCode CLI backend."""
from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..ai.contracts import BackendMode, BackendResult
from ..config.defaults import DEFAULT_OPENCODE_COMMAND
from ..ai.errors import BackendError
from ..project.instructions import ensure_instruction_file, update_goal_reference
from .base import BaseBackend

OPENCODE_CONFIG_CONTENT = "OPENCODE_CONFIG_CONTENT"


class OpenCodeBackend(BaseBackend):
    name = "opencode"
    default_command = DEFAULT_OPENCODE_COMMAND
    supports_sandbox = True

    @classmethod
    def configure_args(
        cls,
        mode: BackendMode,
        extra_args: Sequence[str],
        *,
        allow_project_read: bool = False,
    ) -> list[str]:
        """Keep non-interactive OpenCode runs deterministic and permission-safe."""
        result = list(extra_args)
        if "--auto" not in result:
            result.append("--auto")
        return result

    def build_command(self, prompt: str, session_id: str) -> list[str]:
        if not prompt.strip():
            raise BackendError("opencode prompt is empty")
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

    def stdin_prompt(self, prompt: str) -> str:
        return prompt

    def decode(self, raw: str) -> BackendResult:
        values = self.parse_json_events(raw)
        if not values:
            return BackendResult(raw)

        session_id = self.find_session_id(values)
        text = self._find_last_text(values)
        return BackendResult(text if text is not None else raw, session_id)

    def error_output(self, raw: str) -> str:
        values = self.parse_json_events(raw)
        if not values:
            return raw
        return self._find_error_message(values) or self._find_last_text(values) or raw

    def prepare_project(self) -> list[Path]:
        return [ensure_opencode_rules(self.root)]

    def update_goal_reference(self, goal_file: str | None) -> None:
        update_goal_reference(self.root, "AGENTS.md", goal_file)

    def process_environment(self) -> dict[str, str]:
        permission = self._permission_policy()
        if not permission:
            return {}

        content: dict[str, Any] = {}
        raw = os.environ.get(OPENCODE_CONFIG_CONTENT, "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as error:
                raise BackendError("invalid OPENCODE_CONFIG_CONTENT") from error
            if not isinstance(parsed, dict):
                raise BackendError("OPENCODE_CONFIG_CONTENT must contain a JSON object")
            content.update(parsed)

        existing = content.get("permission")
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(permission)
        content["permission"] = merged
        return {OPENCODE_CONFIG_CONTENT: json.dumps(content, separators=(",", ":"))}

    def _permission_policy(self) -> dict[str, Any]:
        if self.mode == "no_tool":
            return {"*": "deny"}
        if self.mode == "planning":
            policy: dict[str, Any] = {"*": "deny"}
            if self.allow_project_read:
                policy.update({
                    "read": "allow",
                    "glob": "allow",
                    "grep": "allow",
                    "lsp": "allow",
                })
            return policy
        if self.mode == "review":
            policy = {
                "edit": "deny",
                "bash": "deny",
                "task": "deny",
            }
            if self.sandbox:
                policy["external_directory"] = "deny"
            return policy
        if self.sandbox:
            # OpenCode has no Qwen-style container flag. Its public isolation
            # primitive is permission policy; runner safety/protection plugins
            # remain the hard project-write guard.
            return {"external_directory": "deny"}
        return {}

    @staticmethod
    def _find_last_text(values: Sequence[Any]) -> str | None:
        texts: list[str] = []
        for value in values:
            items = value if isinstance(value, list) else [value]
            for item in items:
                if not isinstance(item, dict) or item.get("type") != "text":
                    continue
                part = item.get("part")
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    texts.append(part["text"])
                elif isinstance(item.get("text"), str):
                    texts.append(item["text"])
        return texts[-1] if texts else None

    @staticmethod
    def _find_error_message(values: Sequence[Any]) -> str | None:
        for value in reversed(values):
            items = value if isinstance(value, list) else [value]
            for item in reversed(items):
                if not isinstance(item, dict) or item.get("type") != "error":
                    continue
                error = item.get("error")
                if isinstance(error, dict):
                    data = error.get("data")
                    if isinstance(data, dict) and isinstance(data.get("message"), str):
                        return data["message"]
                    if isinstance(error.get("message"), str):
                        return error["message"]
                if isinstance(error, str):
                    return error
        return None

    @staticmethod
    def extract_diagnostics(values: Sequence[Any], error_text: str = "") -> dict[str, Any]:
        diagnostics = BaseBackend.extract_diagnostics(values, error_text)
        for value in values:
            items = value if isinstance(value, list) else [value]
            for item in items:
                if not isinstance(item, dict) or item.get("type") != "step_finish":
                    continue
                part = item.get("part")
                if not isinstance(part, dict):
                    continue
                tokens = part.get("tokens")
                if not isinstance(tokens, dict):
                    continue
                for source, target in (("input", "input_tokens"), ("output", "output_tokens")):
                    token = tokens.get(source)
                    if isinstance(token, (int, float)):
                        diagnostics[target] = int(token)
                cache = tokens.get("cache")
                if isinstance(cache, dict) and isinstance(cache.get("read"), (int, float)):
                    diagnostics["cache_read_input_tokens"] = int(cache["read"])
                total = sum(
                    int(tokens.get(name, 0))
                    for name in ("input", "output", "reasoning")
                    if isinstance(tokens.get(name, 0), (int, float))
                )
                if total:
                    diagnostics["total_tokens"] = total
        return diagnostics


def ensure_opencode_rules(root: Path) -> Path:
    """Create or extend the OpenCode project rule file."""
    return ensure_instruction_file(root, "AGENTS.md")
