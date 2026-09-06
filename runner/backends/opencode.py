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
_PERMISSION_ACTIONS = frozenset({"allow", "ask", "deny"})


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

        content["permission"] = _merge_permission_cap(content.get("permission"), permission)
        self._apply_agent_permission_cap(content, permission)
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
                    # Keep the legacy option name for YAML/API compatibility, but
                    # Planning read access is intentionally not project-root scoped.
                    "external_directory": "allow",
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
            # primitive is permission policy. Deny subagent delegation too: an
            # OpenCode subagent owns its own permissions and could otherwise
            # bypass the parent agent's external-directory restriction.
            return {"external_directory": "deny", "task": "deny"}
        return {}

    def _apply_agent_permission_cap(
        self,
        content: dict[str, Any],
        permission: dict[str, Any],
    ) -> None:
        """Apply Runner capability limits at the active-agent layer too.

        OpenCode merges per-agent permissions after global permissions, so a
        configured agent can otherwise re-allow an action denied by the Runner.
        Inline config has high precedence, so a partial agent override is enough
        to cap the active agent without replacing its prompt/model settings.
        """
        agents = content.get("agent")
        if agents is None:
            agents = {}
        elif not isinstance(agents, dict):
            raise BackendError("OPENCODE_CONFIG_CONTENT agent must be a JSON object")
        else:
            agents = dict(agents)

        names = set(agents)
        selected = self._selected_agent(content)
        if selected:
            names.add(selected)

        for name in names:
            value = agents.get(name)
            if value is None:
                value = {}
            elif not isinstance(value, dict):
                raise BackendError(
                    f"OPENCODE_CONFIG_CONTENT agent.{name} must be a JSON object"
                )
            else:
                value = dict(value)
            value["permission"] = _merge_permission_cap(value.get("permission"), permission)
            agents[name] = value

        if agents:
            content["agent"] = agents

    def _selected_agent(self, content: dict[str, Any]) -> str:
        for index, value in enumerate(self.extra_args):
            if value == "--agent" and index + 1 < len(self.extra_args):
                return self.extra_args[index + 1].strip()
            if value.startswith("--agent="):
                return value.split("=", 1)[1].strip()
        default_agent = content.get("default_agent")
        if isinstance(default_agent, str) and default_agent.strip():
            return default_agent.strip()
        # OpenCode's default primary agent when no explicit/default agent exists.
        return "build"

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


def _normalize_permission(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        if value not in _PERMISSION_ACTIONS:
            raise BackendError(f"invalid OpenCode permission action: {value}")
        return {"*": value}
    if isinstance(value, dict):
        return dict(value)
    raise BackendError("OpenCode permission must be an action or JSON object")


def _permission_intersection(user_rule: Any, runner_action: str) -> Any:
    """Return a rule no broader than either user policy or Runner cap."""
    if runner_action == "deny":
        return "deny"
    if user_rule is None:
        return runner_action
    if isinstance(user_rule, dict):
        # Runner currently only grants explicit exceptions from a deny-all cap.
        # Keeping a user's granular rule preserves any stricter deny/ask entries.
        return dict(user_rule)
    if isinstance(user_rule, str) and user_rule in _PERMISSION_ACTIONS:
        rank = {"deny": 0, "ask": 1, "allow": 2}
        return user_rule if rank[user_rule] <= rank[runner_action] else runner_action
    return runner_action


def _merge_permission_cap(existing: Any, runner_policy: dict[str, Any]) -> dict[str, Any]:
    """Merge Runner permissions as a capability ceiling, never an expansion."""
    original = _normalize_permission(existing)
    wildcard = runner_policy.get("*")

    if wildcard in _PERMISSION_ACTIONS:
        # A Runner wildcard is authoritative. Explicit Runner exceptions may only
        # restore capability that the user's original policy also permits.
        result: dict[str, Any] = {"*": wildcard}
        for key, runner_action in runner_policy.items():
            if key == "*":
                continue
            user_rule = original.get(key, original.get("*"))
            result[key] = _permission_intersection(user_rule, runner_action)
        return result

    result = dict(original)
    for key, runner_action in runner_policy.items():
        if runner_action == "deny":
            result[key] = "deny"
            continue
        user_rule = original.get(key, original.get("*"))
        result[key] = _permission_intersection(user_rule, runner_action)
    return result


def ensure_opencode_rules(root: Path) -> Path:
    """Create or extend the OpenCode project rule file."""
    return ensure_instruction_file(root, "AGENTS.md")
