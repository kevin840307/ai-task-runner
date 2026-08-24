"""Qwen-specific capability and tool argument policy."""
from __future__ import annotations

from collections.abc import Sequence

from ..ai.contracts import BackendMode

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
QWEN_REVIEW_EXCLUDED_TOOLS = (
    "write_file",
    "edit",
    "notebook_edit",
    "run_shell_command",
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
        excluded = tuple(
            tool
            for tool in QWEN_PLANNING_EXCLUDED_TOOLS
            if (
                tool not in QWEN_PLANNING_PROJECT_READ_TOOLS
                if allow_project_read and mode == "planning"
                else tool != QWEN_NO_TOOL_COMPAT_TOOL
            )
        )
        exclude_qwen_tools(result, excluded)
        ensure_qwen_compat_tool(result)
        return result

    ensure_qwen_yolo(result)
    ensure_qwen_max_tool_calls(result)
    exclude_qwen_tools(result, QWEN_RUNTIME_EXCLUDED_TOOLS)
    ensure_qwen_compat_tool(result)
    if mode == "review":
        exclude_qwen_tools(result, QWEN_REVIEW_EXCLUDED_TOOLS)
        ensure_qwen_compat_tool(result)
    return result


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


def ensure_qwen_max_tool_calls(args: list[str]) -> None:
    if "--max-tool-calls" not in args:
        args.extend(["--max-tool-calls", QWEN_DEFAULT_MAX_TOOL_CALLS])


def exclude_qwen_tools(args: list[str], tool_names: Sequence[str]) -> None:
    for tool_name in tool_names:
        if tool_name not in args:
            args.extend(["--exclude-tools", tool_name])
