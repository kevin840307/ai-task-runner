"""Backend-specific agent argument policy."""
from __future__ import annotations

from typing import Sequence


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

QWEN_PLANNING_EXCLUDED_TOOLS = (
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


def planning_agent_args(backend: str, extra_args: Sequence[str]) -> list[str]:
    """Preserve Qwen planning permissions while trimming custom context load."""
    result = list(extra_args)
    if backend == "qwen":
        ensure_qwen_yolo(result)
        ensure_qwen_safe_mode(result)
        exclude_qwen_tools(result, QWEN_PLANNING_EXCLUDED_TOOLS)
    return result


def runtime_agent_args(backend: str, extra_args: Sequence[str]) -> list[str]:
    result = list(extra_args)
    if backend == "qwen":
        ensure_qwen_yolo(result)
        exclude_qwen_tools(result, QWEN_RUNTIME_EXCLUDED_TOOLS)
    return result


def ensure_qwen_yolo(args: list[str]) -> None:
    if "--yolo" not in args and "--approval-mode" not in args:
        args.append("--yolo")


def ensure_qwen_safe_mode(args: list[str]) -> None:
    if "--safe-mode" not in args:
        args.append("--safe-mode")


def exclude_qwen_tools(args: list[str], tool_names: Sequence[str]) -> None:
    for tool_name in tool_names:
        if tool_name not in args:
            args.extend(["--exclude-tools", tool_name])
