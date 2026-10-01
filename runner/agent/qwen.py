"""Qwen CLI agent backend and capability policy."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..config.defaults import DEFAULT_QWEN_COMMAND
from ..runtime.process_runner import run_process
from ..utils import io_path
from ..workspace import ensure_instruction_file, update_goal_reference
from .backend import BackendError, BackendMode, BackendResult, BaseBackend

QWEN_DEFAULT_MAX_TOOL_CALLS = "-1"
QWEN_COMPUTER_USE_TOOLS = (
    "computer_use__bring_to_front",
    "computer_use__check_for_update",
    "computer_use__check_permissions",
    "computer_use__launch_app",
    "computer_use__kill_app",
    "computer_use__hotkey",
    "computer_use__list_apps",
    "computer_use__list_windows",
    "computer_use__get_accessibility_tree",
    "computer_use__get_agent_cursor_state",
    "computer_use__get_config",
    "computer_use__get_cursor_position",
    "computer_use__get_recording_state",
    "computer_use__get_screen_size",
    "computer_use__get_window_state",
    "computer_use__screenshot",
    "computer_use__click",
    "computer_use__double_click",
    "computer_use__right_click",
    "computer_use__press_key",
    "computer_use__type_text",
    "computer_use__scroll",
    "computer_use__move_cursor",
    "computer_use__drag",
    "computer_use__page",
    "computer_use__replay_trajectory",
    "computer_use__set_agent_cursor_enabled",
    "computer_use__set_agent_cursor_motion",
    "computer_use__set_agent_cursor_style",
    "computer_use__set_config",
    "computer_use__set_value",
    "computer_use__start_recording",
    "computer_use__stop_recording",
    "computer_use__end_session",
    "computer_use__start_session",
    "computer_use__zoom",
    "bring_to_front",
    "check_for_update",
    "check_permissions",
    "launch_app",
    "kill_app",
    "hotkey",
    "list_apps",
    "list_windows",
    "get_accessibility_tree",
    "get_agent_cursor_state",
    "get_config",
    "get_cursor_position",
    "get_recording_state",
    "get_screen_size",
    "get_window_state",
    "screenshot",
    "click",
    "double_click",
    "right_click",
    "press_key",
    "type_text",
    "scroll",
    "move_cursor",
    "drag",
    "page",
    "replay_trajectory",
    "set_agent_cursor_enabled",
    "set_agent_cursor_motion",
    "set_agent_cursor_style",
    "set_config",
    "set_value",
    "start_recording",
    "stop_recording",
    "end_session",
    "start_session",
    "zoom",
)
QWEN_NO_TOOL_COMPAT_TOOL = "read_file"
QWEN_PLANNING_PROJECT_READ_TOOLS = (
    "read_file",
    "read_many_files",
    "list_directory",
    "glob",
    "grep_search",
    "search_file_content",
)
QWEN_PLANNING_EXCLUDED_TOOLS = (
    "read_file",
    "read_many_files",
    "list_directory",
    "glob",
    "grep_search",
    "search_file_content",
    "read_mcp_resource",
    "send_message",
    "cron_create",
    "cron_list",
    "cron_delete",
    "list_agents",
    "task_stop",
    "web_fetch",
    "record_artifact",
    "loop_wakeup",
    "create_sub_session",
    "enter_worktree",
    "exit_worktree",
    "monitor",
    "write_file",
    "edit",
    "notebook_edit",
    "run_shell_command",
    "tool_search",
    "todo_write",
    "skill",
    "agent",
    *QWEN_COMPUTER_USE_TOOLS,
)
QWEN_RUNTIME_EXCLUDED_TOOLS = (
    "todo_write",
    "skill",
    "agent",
    *QWEN_COMPUTER_USE_TOOLS,
)


def configure_qwen_args(
    mode: BackendMode,
    extra_args: Sequence[str],
    *,
    allow_project_read: bool = False,
) -> list[str]:
    """Apply Qwen's capability policy for one runner stage."""
    result = list(extra_args)
    if mode in ("planning", "no_tool"):
        ensure_qwen_yolo(result)
        ensure_qwen_safe_mode(result)
        exclude_qwen_tools(
            result,
            qwen_readonly_excluded_tools(
                allow_project_read=allow_project_read and mode == "planning"
            ),
        )
        ensure_qwen_compat_tool(result)
        return result

    if mode == "review":
        ensure_qwen_yolo(result)
        ensure_qwen_safe_mode(result)
        ensure_qwen_max_tool_calls(result)
        exclude_qwen_tools(result, qwen_readonly_excluded_tools(allow_project_read=True))
        ensure_qwen_compat_tool(result)
        return result

    if mode == "validation":
        ensure_qwen_yolo(result)
        ensure_qwen_max_tool_calls(result)
        exclude_qwen_tools(
            result,
            (
                "edit",
                "notebook_edit",
                "todo_write",
                "skill",
                "agent",
                *QWEN_COMPUTER_USE_TOOLS,
            ),
        )
        ensure_qwen_compat_tool(result)
        return result

    ensure_qwen_yolo(result)
    ensure_qwen_max_tool_calls(result)
    exclude_qwen_tools(result, QWEN_RUNTIME_EXCLUDED_TOOLS)
    ensure_qwen_compat_tool(result)
    return result


def qwen_readonly_excluded_tools(*, allow_project_read: bool) -> tuple[str, ...]:
    return tuple(
        tool
        for tool in QWEN_PLANNING_EXCLUDED_TOOLS
        if (
            tool not in QWEN_PLANNING_PROJECT_READ_TOOLS
            if allow_project_read
            else tool != QWEN_NO_TOOL_COMPAT_TOOL
        )
    )


def ensure_qwen_compat_tool(args: list[str]) -> None:
    """Keep one built-in read-only tool available for strict API schemas."""
    joined = f"--exclude-tools={QWEN_NO_TOOL_COMPAT_TOOL}"
    args[:] = [value for value in args if value != joined]
    index = 0
    while index < len(args) - 1:
        if args[index] == "--exclude-tools" and args[index + 1] == QWEN_NO_TOOL_COMPAT_TOOL:
            del args[index:index + 2]
            continue
        index += 1


def ensure_qwen_yolo(args: list[str]) -> None:
    if "--yolo" not in args and "--approval-mode" not in args:
        args.append("--yolo")


def ensure_qwen_safe_mode(args: list[str]) -> None:
    if "--safe-mode" not in args:
        args.append("--safe-mode")


def ensure_qwen_max_tool_calls(
    args: list[str],
    value: str = QWEN_DEFAULT_MAX_TOOL_CALLS,
) -> None:
    if "--max-tool-calls" not in args:
        args.extend(["--max-tool-calls", value])


def exclude_qwen_tools(args: list[str], tool_names: Sequence[str]) -> None:
    for tool_name in tool_names:
        if tool_name not in args:
            args.extend(["--exclude-tools", tool_name])

class QwenBackend(BaseBackend):
    name = "qwen"
    default_command = DEFAULT_QWEN_COMMAND
    sandbox_flags = ("-s", "--sandbox")
    supports_sandbox = True

    @classmethod
    def configure_args(
        cls,
        mode: BackendMode,
        extra_args: Sequence[str],
        *,
        allow_project_read: bool = False,
    ) -> list[str]:
        return configure_qwen_args(
            mode,
            extra_args,
            allow_project_read=allow_project_read,
        )

    def build_command(self, prompt: str, session_id: str) -> list[str]:
        if not prompt.strip():
            raise BackendError("qwen prompt is empty")
        if session_id and any(
            value in {"-s", "--sandbox"} for value in self.extra_args
        ):
            bridge_sandbox_session(self.root, session_id)
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
        if result is not None and self._api_error_envelope(result):
            raise BackendError(
                result.strip(),
                session_id=session_id,
                output=raw,
                command_mode="decoded-success-error",
                diagnostics={"api_error_envelope": True},
                recovery_key="qwen:api-error-envelope",
            )
        return BackendResult(result if result is not None else raw, session_id)

    @staticmethod
    def _api_error_envelope(text: str) -> bool:
        value = str(text or "").strip()
        return value.startswith("[API Error:") and value.endswith("]")

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

    def update_goal_reference(self, goal_file: str | None) -> None:
        update_qwen_goal_reference(self.root, goal_file)

    def context_snapshot(self, session_id: str) -> str:
        """Run Qwen's read-only /context display command for diagnostics only."""
        return self._session_command(session_id, "/context", timeout=30)

    def context_usage_percent(self, snapshot: str) -> float | None:
        match = re.search(r"Used\s+[0-9.]+[kKmM]?\s+tokens\s+\(([0-9.]+)%\)", snapshot)
        return float(match.group(1)) if match else None

    def compress_session(self, session_id: str) -> str:
        """Use Qwen's non-AI fast compaction on an existing session."""
        return self._session_command(session_id, "/compress-fast", timeout=60)

    def _session_command(self, session_id: str, command: str, timeout: int) -> str:
        if not session_id:
            return ""
        if any(value in self.sandbox_flags for value in self.extra_args):
            bridge_sandbox_session(self.root, session_id)
        try:
            result = run_process(
                [*self.base_command, "-p", command, "--resume", session_id, *self.extra_args],
                self.root,
                min(self.timeout, timeout),
            )
        except Exception as error:
            return f"ERROR: {type(error).__name__}: {error}"
        output = result.output.strip()
        if result.timed_out:
            return f"ERROR: {command} timed out | {output}".strip()
        if result.return_code:
            return f"ERROR: {command} exit {result.return_code} | {output}".strip()
        return output

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
    return ensure_instruction_file(root, "QWEN.md")

def bridge_sandbox_session(
    root: Path,
    session_id: str,
    projects: Path | None = None,
) -> None:
    """Expose a container-recorded chat at Qwen's host project path."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", session_id):
        raise BackendError("invalid Qwen session id")
    projects = projects or Path.home() / ".qwen" / "projects"
    project_root = str(root.resolve())
    if os.name == "nt":
        project_root = project_root.lower()
    project_id = re.sub(r"[^a-zA-Z0-9]", "-", project_root)
    target = projects / project_id / "chats" / f"{session_id}.jsonl"
    try:
        sources = [
            path for path in projects.glob(f"*/chats/{session_id}.jsonl")
            if path != target
        ]
        if not sources:
            return
        source = max(sources, key=lambda path: path.stat().st_mtime_ns)
        io_path(target.parent).mkdir(parents=True, exist_ok=True)
        lines = []
        for line in io_path(source).read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if isinstance(record, dict) and "cwd" in record:
                record["cwd"] = str(root.resolve())
            lines.append(json.dumps(
                record, ensure_ascii=False, separators=(",", ":")
            ))
        temporary = target.with_suffix(".jsonl.tmp")
        io_path(temporary).write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(io_path(temporary), io_path(target))
    except (OSError, json.JSONDecodeError) as error:
        raise BackendError("invalid Qwen sandbox session") from error




def update_qwen_goal_reference(root: Path, goal_file: str | None) -> Path:
    return update_goal_reference(root, "QWEN.md", goal_file)

__all__ = [
    "QwenBackend",
    "bridge_sandbox_session",
    "configure_qwen_args",
    "ensure_qwen_rules",
    "update_qwen_goal_reference",
]
