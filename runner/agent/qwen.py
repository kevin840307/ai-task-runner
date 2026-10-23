"""Qwen CLI agent backend and capability policy."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..config.defaults import DEFAULT_QWEN_COMMAND
from ..runtime.process_runner import run_process, terminate_process_tree
from ..utils import io_path
from ..workspace import ensure_instruction_file, update_goal_reference
from .backend import BackendError, BackendMode, BackendResult, BaseBackend, CapabilitySpec, ChatFeatureSpec, InteractionMode, InteractionModeSpec, ReasoningOptionSpec

QWEN_DEFAULT_MAX_TOOL_CALLS = "-1"
_QWEN_PROJECT_CHAT_FEATURES = frozenset({
    "session_create",
    "session_id_override",
    "session_scope_override",
    "session_resume",
    "session_prompt",
    "session_events",
    "session_permission_vote",
    "session_status",
    "session_set_model",
    "session_close",
})
_QWEN_AUTH_TYPES = {
    "openai",
    "openai-responses",
    "qwen-oauth",
    "gemini",
    "vertex-ai",
    "anthropic",
}
_QWEN_AUTH_MODEL_ENV_VARS = {
    "openai": ("OPENAI_MODEL", "QWEN_MODEL"),
    "openai-responses": ("OPENAI_MODEL",),
    "qwen-oauth": (),
    "gemini": ("GEMINI_MODEL",),
    "vertex-ai": ("GOOGLE_MODEL",),
    "anthropic": ("ANTHROPIC_MODEL",),
}
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
def _qwen_cli_version(root: Path) -> tuple[int, int, int]:
    try:
        result = run_process([DEFAULT_QWEN_COMMAND, "--version"], root, 5)
    except Exception as exc:
        raise BackendError(f"Qwen version discovery failed: {exc}") from exc
    if result.return_code or result.timed_out:
        detail = result.output.strip() or f"exit {result.return_code}"
        raise BackendError(f"Qwen version discovery failed: {detail[-1000:]}")
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)", result.output)
    if not match:
        raise BackendError("Qwen version discovery returned an unrecognized version")
    return tuple(int(value) for value in match.groups())


def _qwen_settings_paths(root: Path) -> tuple[Path, ...]:
    qwen_home = Path(os.environ.get("QWEN_HOME") or (Path.home() / ".qwen")).expanduser()
    if os.name == "nt":
        program_data = Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
        system_defaults = program_data / "qwen-code" / "system-defaults.json"
        system_settings = program_data / "qwen-code" / "settings.json"
    elif sys.platform == "darwin":
        base = Path("/Library/Application Support/QwenCode")
        system_defaults = base / "system-defaults.json"
        system_settings = base / "settings.json"
    else:
        system_defaults = Path("/etc/qwen-code/system-defaults.json")
        system_settings = Path("/etc/qwen-code/settings.json")
    system_defaults = Path(
        os.environ.get("QWEN_CODE_SYSTEM_DEFAULTS_PATH") or system_defaults
    ).expanduser()
    system_settings = Path(
        os.environ.get("QWEN_CODE_SYSTEM_SETTINGS_PATH") or system_settings
    ).expanduser()
    return (
        system_defaults,
        qwen_home / "settings.json",
        root / ".qwen" / "settings.json",
        system_settings,
    )


def _read_qwen_settings(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    # Qwen settings are JSON-with-comments. Strip comments without touching strings.
    out: list[str] = []
    i = 0
    quoted = False
    escaped = False
    while i < len(raw):
        ch = raw[i]
        if quoted:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
            i += 1
            continue
        if ch == '"':
            quoted = True
            out.append(ch)
            i += 1
            continue
        if raw.startswith("//", i):
            end = raw.find("\n", i)
            i = len(raw) if end < 0 else end
            continue
        if raw.startswith("/*", i):
            end = raw.find("*/", i + 2)
            i = len(raw) if end < 0 else end + 2
            continue
        out.append(ch)
        i += 1
    try:
        value = json.loads("".join(out))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _qwen_replace_setting(
    layers: Sequence[dict[str, Any]],
    key: str,
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for settings in layers:
        candidate = settings.get(key)
        if isinstance(candidate, dict):
            value = candidate
    return value


def _qwen_selected_model(layers: Sequence[dict[str, Any]]) -> str:
    value = ""
    for settings in layers:
        model = settings.get("model")
        if isinstance(model, dict) and isinstance(model.get("name"), str):
            value = model["name"].strip()
    return value


def _qwen_selected_auth_type(layers: Sequence[dict[str, Any]]) -> str:
    value = ""
    for settings in layers:
        security = settings.get("security")
        auth = security.get("auth") if isinstance(security, dict) else None
        selected = auth.get("selectedType") if isinstance(auth, dict) else None
        if isinstance(selected, str) and selected.strip():
            value = selected.strip()
    if value in _QWEN_AUTH_TYPES:
        return value

    if os.environ.get("QWEN_OAUTH"):
        return "qwen-oauth"
    if (
        os.environ.get("OPENAI_API_KEY")
        and (os.environ.get("OPENAI_MODEL") or os.environ.get("QWEN_MODEL"))
        and os.environ.get("OPENAI_BASE_URL")
    ):
        return "openai"
    if os.environ.get("GEMINI_API_KEY") and os.environ.get("GEMINI_MODEL"):
        return "gemini"
    if os.environ.get("GOOGLE_API_KEY") and os.environ.get("GOOGLE_MODEL"):
        return "vertex-ai"
    if os.environ.get("GOOGLE_CLOUD_PROJECT") and os.environ.get("GOOGLE_MODEL"):
        return "vertex-ai"
    if (
        os.environ.get("ANTHROPIC_API_KEY")
        and os.environ.get("ANTHROPIC_MODEL")
        and os.environ.get("ANTHROPIC_BASE_URL")
    ):
        return "anthropic"
    return ""


def _qwen_model_protocol(
    provider_id: str,
    model: dict[str, Any],
    provider_protocol: dict[str, Any],
) -> str:
    protocol = provider_protocol.get(provider_id, provider_id)
    if not isinstance(protocol, str) or protocol not in _QWEN_AUTH_TYPES:
        return ""
    wire_api = model.get("wireApi")
    if wire_api is None:
        return str(protocol)
    if (
        wire_api not in ("chat-completions", "responses")
        or protocol not in ("openai", "openai-responses")
    ):
        return ""
    return "openai-responses" if wire_api == "responses" else "openai"


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



def _qwen_serve_command(root: Path) -> list[str]:
    executable = shutil.which(DEFAULT_QWEN_COMMAND) or DEFAULT_QWEN_COMMAND
    args = [
        executable,
        "serve",
        "--no-web",
        "--workspace",
        str(root),
        "--port",
        "0",
    ]
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", *args]
    return args


def _qwen_http_json_response(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    client_id: str = "",
    timeout: float = 8,
) -> tuple[int, dict[str, Any]]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers: dict[str, str] = {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if client_id:
        headers["X-Qwen-Client-Id"] = client_id
    request = urllib.request.Request(
        base_url + path,
        data=payload,
        method=method,
        headers=headers,
    )
    status = 0
    raw = ""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        raw = exc.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError) as exc:
        raise BackendError(f"Qwen daemon request failed: {exc}") from exc
    if not raw.strip():
        return status, {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BackendError("Qwen daemon returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise BackendError("Qwen daemon returned invalid payload")
    return status, value


def _qwen_http_error(
    status: int,
    payload: dict[str, Any],
    *,
    method: str,
    path: str,
) -> BackendError:
    detail = (
        payload.get("message")
        or payload.get("error")
        or payload.get("code")
        or payload
        or f"HTTP {status}"
    )
    if isinstance(detail, (dict, list)):
        detail = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
    return BackendError(
        f"Qwen daemon {method} {path} failed (HTTP {status}): {detail}"
    )


def _qwen_http_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    client_id: str = "",
    timeout: float = 8,
) -> dict[str, Any]:
    status, value = _qwen_http_json_response(
        base_url,
        path,
        method=method,
        body=body,
        client_id=client_id,
        timeout=timeout,
    )
    if status >= 400:
        raise _qwen_http_error(status, value, method=method, path=path)
    return value


@contextmanager
def _qwen_daemon_process(
    root: Path,
    *,
    environment: dict[str, str] | None = None,
) -> Iterator[tuple[str, set[str]]]:
    """Own one short-lived qwen serve process and expose its native feature set."""
    command = _qwen_serve_command(root)
    options: dict[str, Any] = {
        "cwd": root,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if environment is not None:
        options["env"] = environment
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **options)
    except OSError as exc:
        raise BackendError(f"Qwen daemon failed to start: {exc}") from exc

    lines: queue.Queue[str] = queue.Queue()

    def reader() -> None:
        stream = process.stdout
        if stream is None:
            return
        for line in stream:
            lines.put(line)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    base_url = ""
    startup: list[str] = []
    try:
        deadline = time.monotonic() + 12
        pattern = re.compile(r"listening on (http://127\.0\.0\.1:(\d+))")
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            startup.append(line.rstrip())
            match = pattern.search(line)
            if match:
                base_url = match.group(1)
                break
        if not base_url:
            detail = "\n".join(startup[-20:]) or f"exit {process.poll()}"
            raise BackendError(f"Qwen daemon did not become ready: {detail}")

        caps = _qwen_http_json(base_url, "/capabilities")
        features = {str(value) for value in caps.get("features") or []}
        yield base_url, features
    finally:
        terminate_process_tree(process)


@contextmanager
def _qwen_daemon_session(
    root: Path,
) -> Iterator[tuple[str, str, set[str]]]:
    """Own one short-lived native Qwen daemon session for catalog discovery."""
    with _qwen_daemon_process(root) as (base_url, features):
        if "session_create" not in features:
            raise BackendError("Qwen capability daemon is missing: session_create")
        create_body: dict[str, Any] = {"cwd": str(root)}
        if "session_scope_override" in features:
            create_body["sessionScope"] = "thread"
        created = _qwen_http_json(base_url, "/session", method="POST", body=create_body)
        session_id = str(created.get("sessionId") or "")
        client_id = str(created.get("clientId") or "")
        if not session_id:
            raise BackendError("Qwen capability daemon did not return sessionId")
        try:
            yield base_url, session_id, features
        finally:
            try:
                _qwen_http_json(
                    base_url,
                    f"/session/{urllib.parse.quote(session_id, safe='')}",
                    method="DELETE",
                    client_id=client_id,
                )
            except BackendError:
                pass


def _qwen_chat_bridge_path(root: Path, session_id: str) -> Path:
    key = hashlib.sha256(
        (str(root.resolve()) + "\0" + str(session_id)).encode("utf-8")
    ).hexdigest()
    return (
        Path(tempfile.gettempdir())
        / "ai-task-runner-qwen-chat"
        / f"{key}.json"
    )


def _qwen_chat_bridge_write(
    root: Path,
    session_id: str,
    value: dict[str, Any],
) -> None:
    path = _qwen_chat_bridge_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _qwen_chat_bridge_read(
    root: Path,
    session_id: str,
) -> dict[str, Any] | None:
    path = _qwen_chat_bridge_path(root, session_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if str(value.get("sessionId") or "") != str(session_id):
        return None
    base_url = str(value.get("baseUrl") or "")
    if not re.fullmatch(r"http://127\.0\.0\.1:\d+", base_url):
        return None
    return value


def _qwen_chat_bridge_delete(root: Path, session_id: str) -> None:
    try:
        _qwen_chat_bridge_path(root, session_id).unlink()
    except OSError:
        pass


@contextmanager
def _qwen_sse_stream(
    base_url: str,
    session_id: str,
    *,
    client_id: str = "",
    last_event_id: int | None = None,
    event_epoch: str = "",
    read_timeout: float = 30,
) -> Iterator[Any]:
    headers = {
        "Accept": "text/event-stream",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    }
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
        if event_epoch:
            headers["X-Qwen-Event-Epoch"] = event_epoch
    if client_id:
        headers["X-Qwen-Client-Id"] = client_id
    path = f"/session/{urllib.parse.quote(session_id, safe='')}/events"
    request = urllib.request.Request(base_url + path, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=read_timeout)
    except (OSError, urllib.error.URLError) as exc:
        raise BackendError(f"Qwen daemon event stream failed: {exc}") from exc
    try:
        yield response
    finally:
        try:
            response.close()
        except OSError:
            pass


def _qwen_sse_events(
    response: Any,
    *,
    deadline: float = 0,
) -> Iterator[dict[str, Any]]:
    for raw_line in response:
        if deadline and time.monotonic() > deadline:
            raise BackendError("Qwen Project Chat daemon turn timed out")
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace").strip()
        else:
            line = str(raw_line).strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise BackendError("Qwen daemon event stream returned invalid JSON") from exc
        if isinstance(value, dict):
            yield value


def _qwen_is_ask_user_question(payload: dict[str, Any]) -> bool:
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return False
    if str(tool_call.get("kind") or "") == "ask_user_question":
        return True
    raw = tool_call.get("rawInput")
    if isinstance(raw, dict) and isinstance(raw.get("questions"), list):
        return True
    meta = tool_call.get("_meta")
    return (
        isinstance(meta, dict)
        and (
            str(meta.get("qwenInteractionKind") or "") == "user_question"
            or isinstance(meta.get("qwenQuestions"), list)
        )
    )

def _qwen_daemon_snapshot(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with _qwen_daemon_session(root) as (base_url, session_id, features):
        required = {"session_supported_commands", "session_resources"}
        missing = sorted(required - features)
        if missing:
            raise BackendError(
                "Qwen capability daemon is missing: " + ", ".join(missing)
            )
        commands = _qwen_http_json(
            base_url,
            f"/session/{session_id}/supported-commands",
        )
        resources = _qwen_http_json(base_url, f"/session/{session_id}/resources")
        return commands, resources


def _qwen_model_ids_from_context(context: dict[str, Any]) -> list[str]:
    state = context.get("state")
    if not isinstance(state, dict):
        return []
    options = state.get("configOptions")
    if not isinstance(options, list):
        return []
    model = next(
        (
            item
            for item in options
            if isinstance(item, dict)
            and (
                str(item.get("category") or "") == "model"
                or str(item.get("id") or "") == "model"
            )
        ),
        None,
    )
    if not isinstance(model, dict):
        return []

    values: set[str] = set()
    current = str(model.get("currentValue") or "").strip()
    if current:
        values.add(current)
    choices = model.get("options")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            value = str(choice.get("value") or choice.get("id") or "").strip()
            if value:
                values.add(value)
    return sorted(values)


def _qwen_native_model_ids(root: Path) -> list[str]:
    with _qwen_daemon_session(root) as (base_url, session_id, features):
        if "session_context" not in features:
            raise BackendError("Qwen capability daemon is missing: session_context")
        context = _qwen_http_json(base_url, f"/session/{session_id}/context")
        values = _qwen_model_ids_from_context(context)
        if not values:
            raise BackendError("Qwen session context did not return model options")
        return values

def _qwen_capability_specs(
    commands: dict[str, Any],
    resources: dict[str, Any],
) -> list[CapabilitySpec]:
    result: list[CapabilitySpec] = []
    seen: set[tuple[str, str]] = set()
    for item in commands.get("availableCommands") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lstrip("/")
        if not name:
            continue
        meta = item.get("_meta") if isinstance(item.get("_meta"), dict) else {}
        key = ("command", name)
        if key in seen:
            continue
        seen.add(key)
        result.append(CapabilitySpec(
            token=f"/{name}",
            name=name,
            description=str(item.get("description") or "").strip(),
            kind="command",
            source=str(meta.get("source") or "qwen"),
            user_invocable=True,
            enabled=True,
            permission="available",
        ))

    skills_payload = resources.get("skills")
    skills = skills_payload.get("skills") if isinstance(skills_payload, dict) else []
    for item in skills or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        user_invocable = item.get("userInvocable") is not False
        status = str(item.get("status") or "ok").strip()
        enabled = status == "ok" and user_invocable
        key = ("skill", name)
        if key in seen:
            continue
        seen.add(key)
        result.append(CapabilitySpec(
            token=f"/{name}",
            name=name,
            description=str(item.get("description") or "").strip(),
            kind="skill",
            source=str(item.get("level") or "qwen"),
            user_invocable=user_invocable,
            enabled=enabled,
            permission="available" if enabled else "disabled",
            availability=status,
        ))

    known_skill_names = {
        item.name for item in result if item.kind == "skill"
    }
    for raw_name in commands.get("availableSkills") or []:
        name = str(raw_name or "").strip()
        if not name or name in known_skill_names:
            continue
        result.append(CapabilitySpec(
            token=f"/{name}",
            name=name,
            description="",
            kind="skill",
            source="qwen",
            user_invocable=True,
            enabled=True,
            permission="available",
        ))
    return sorted(result, key=lambda item: (item.token.lower(), item.kind))



_QWEN_REASONING_LABELS = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra high",
    "max": "Max",
}
_QWEN_REASONING_ORDER = tuple(_QWEN_REASONING_LABELS)


def _qwen_reasoning_options(root: Path, model: str) -> tuple[ReasoningOptionSpec, ...]:
    layers = [_read_qwen_settings(path) for path in _qwen_settings_paths(root)]
    providers = _qwen_replace_setting(layers, "modelProviders")
    selected = str(model or "").strip() or _qwen_selected_model(layers)
    configured: dict[str, Any] | None = None
    for items in providers.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or str(item.get("id") or "").strip() != selected:
                continue
            configured = item
            break
        if configured is not None:
            break

    efforts = list(_QWEN_REASONING_ORDER)
    default = ""
    if configured is not None:
        capabilities = configured.get("capabilities")
        reasoning = capabilities.get("reasoning") if isinstance(capabilities, dict) else None
        if reasoning is False:
            return ()
        if isinstance(reasoning, dict):
            raw_efforts = reasoning.get("efforts")
            if raw_efforts is None:
                raw_efforts = reasoning.get("effort")
            if isinstance(raw_efforts, list):
                narrowed = [
                    str(value).strip().lower()
                    for value in raw_efforts
                    if str(value).strip().lower() in _QWEN_REASONING_LABELS
                ]
                if narrowed:
                    efforts = [value for value in _QWEN_REASONING_ORDER if value in narrowed]
            default = str(
                reasoning.get("defaultEffort")
                or reasoning.get("default")
                or ""
            ).strip().lower()

    model_settings: dict[str, Any] = {}
    for settings in layers:
        candidate = settings.get("model")
        if isinstance(candidate, dict):
            model_settings.update(candidate)
    selected_effort = str(model_settings.get("reasoningEffort") or "").strip().lower()
    if selected_effort in efforts:
        default = selected_effort

    return tuple(
        ReasoningOptionSpec(
            id=value,
            label=_QWEN_REASONING_LABELS[value],
            native=value,
            description="Qwen /effort tier; the active provider may map or clamp it.",
            default=value == default,
        )
        for value in efforts
    )


class QwenBackend(BaseBackend):
    def configure_reasoning(self, reasoning: str) -> None:
        super().configure_reasoning(reasoning)
        self._reasoning_settings_path = None

    def process_environment(self) -> dict[str, str]:
        if not self.reasoning:
            return {}
        current = getattr(self, "_reasoning_settings_path", None)
        if isinstance(current, Path) and current.is_file():
            return {"QWEN_CODE_SYSTEM_SETTINGS_PATH": str(current)}

        source = _qwen_settings_paths(self.root)[-1]
        settings = _read_qwen_settings(source)
        model = settings.get("model")
        model_settings = dict(model) if isinstance(model, dict) else {}
        model_settings["reasoningEffort"] = self.reasoning
        settings = dict(settings)
        settings["model"] = model_settings

        handle, raw_path = tempfile.mkstemp(
            prefix="ai-task-runner-qwen-chat-",
            suffix=".json",
        )
        os.close(handle)
        path = Path(raw_path)
        path.write_text(
            json.dumps(settings, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        self._reasoning_settings_path = path
        return {"QWEN_CODE_SYSTEM_SETTINGS_PATH": str(path)}

    def _cleanup_reasoning_settings(self) -> None:
        path = getattr(self, "_reasoning_settings_path", None)
        self._reasoning_settings_path = None
        if isinstance(path, Path):
            try:
                path.unlink()
            except OSError:
                pass

    def ask(
        self,
        prompt: str,
        session_id: str = "",
        idle_timeout_after_change: float = 0,
        change_detected=None,
    ) -> BackendResult:
        try:
            if self.interaction_mode is not None:
                return self._ask_project_chat(prompt, session_id)
            return super().ask(
                prompt,
                session_id,
                idle_timeout_after_change,
                change_detected,
            )
        finally:
            self._cleanup_reasoning_settings()

    def _ask_project_chat(self, prompt: str, session_id: str) -> BackendResult:
        if not prompt.strip():
            raise BackendError("qwen prompt is empty")
        session_id = self.ensure_native_session(self.root, session_id)
        native_mode = next(
            item.native
            for item in self.interaction_modes()
            if item.id == self.interaction_mode
        )
        environment = dict(os.environ)
        environment.update(self.process_environment())
        encoded_session = urllib.parse.quote(session_id, safe="")
        model = self.model_from_args(self.extra_args)
        required = _QWEN_PROJECT_CHAT_FEATURES

        with _qwen_daemon_process(
            self.root,
            environment=environment,
        ) as (base_url, features):
            missing = sorted(required - features)
            if missing:
                raise BackendError(
                    "Qwen Project Chat daemon is missing: " + ", ".join(missing)
                )

            restore_body = {
                "cwd": str(self.root),
                "approvalMode": native_mode,
            }
            status, live = _qwen_http_json_response(
                base_url,
                f"/session/{encoded_session}/resume",
                method="POST",
                body=restore_body,
                timeout=90,
            )
            if status == 404:
                create_body: dict[str, Any] = {
                    "cwd": str(self.root),
                    "sessionId": session_id,
                    "approvalMode": native_mode,
                }
                create_body["sessionScope"] = "thread"
                live = _qwen_http_json(
                    base_url,
                    "/session",
                    method="POST",
                    body=create_body,
                    timeout=90,
                )
            elif status >= 400:
                raise _qwen_http_error(
                    status,
                    live,
                    method="POST",
                    path=f"/session/{encoded_session}/resume",
                )

            actual_session = str(live.get("sessionId") or session_id)
            if actual_session.lower() != session_id.lower():
                raise BackendError(
                    "Qwen daemon returned a different Project Chat session id"
                )
            client_id = str(live.get("clientId") or "")
            if model:
                _qwen_http_json(
                    base_url,
                    f"/session/{encoded_session}/model",
                    method="POST",
                    body={"modelId": model},
                    client_id=client_id,
                    timeout=30,
                )
            if self.reasoning:
                _qwen_http_json(
                    base_url,
                    f"/session/{encoded_session}/config-option",
                    method="POST",
                    body={
                        "configId": "reasoning_effort",
                        "value": self.reasoning,
                        "persist": False,
                    },
                    client_id=client_id,
                    timeout=30,
                )

            status_snapshot = _qwen_http_json(
                base_url,
                f"/session/{encoded_session}/status",
                client_id=client_id,
                timeout=8,
            )
            cursor = status_snapshot.get("lastEventId")
            if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
                raise BackendError(
                    "Qwen Project Chat daemon did not return a valid event cursor"
                )
            event_epoch = str(live.get("eventEpoch") or "").strip()

            bridge: dict[str, Any] = {
                "sessionId": session_id,
                "baseUrl": base_url,
                "clientId": client_id,
                "ownerPid": os.getpid(),
                "pending": None,
            }
            _qwen_chat_bridge_write(self.root, session_id, bridge)
            try:
                with _qwen_sse_stream(
                    base_url,
                    session_id,
                    client_id=client_id,
                    last_event_id=cursor,
                    event_epoch=event_epoch,
                    read_timeout=max(30, self.timeout + 30),
                ) as stream:
                    admitted = _qwen_http_json(
                        base_url,
                        f"/session/{encoded_session}/prompt",
                        method="POST",
                        body={
                            "prompt": [{
                                "type": "text",
                                "text": prompt,
                            }]
                        },
                        client_id=client_id,
                        timeout=30,
                    )
                    prompt_id = str(admitted.get("promptId") or "")
                    if not prompt_id:
                        raise BackendError(
                            "Qwen Project Chat daemon did not return promptId"
                        )

                    chunks: list[str] = []
                    deadline = time.monotonic() + max(1, self.timeout)
                    for event in _qwen_sse_events(stream, deadline=deadline):
                        event_type = str(event.get("type") or "")
                        data = event.get("data")
                        if not isinstance(data, dict):
                            data = {}
                        event_prompt = str(
                            data.get("promptId")
                            or event.get("promptId")
                            or ""
                        )
                        if event_prompt and event_prompt != prompt_id:
                            continue

                        if event_type == "session_update":
                            update = data.get("update")
                            if (
                                isinstance(update, dict)
                                and update.get("sessionUpdate") == "agent_message_chunk"
                            ):
                                content = update.get("content")
                                if isinstance(content, dict):
                                    text = str(content.get("text") or "")
                                    if text:
                                        chunks.append(text)
                            continue

                        if event_type == "permission_request":
                            request_id = str(data.get("requestId") or "")
                            if not request_id:
                                continue
                            if _qwen_is_ask_user_question(data):
                                bridge["pending"] = data
                                _qwen_chat_bridge_write(
                                    self.root,
                                    session_id,
                                    bridge,
                                )
                            else:
                                _qwen_http_json(
                                    base_url,
                                    (
                                        f"/session/{encoded_session}/permission/"
                                        + urllib.parse.quote(request_id, safe="")
                                    ),
                                    method="POST",
                                    body={"outcome": {"outcome": "cancelled"}},
                                    client_id=client_id,
                                    timeout=30,
                                )
                            continue

                        if event_type == "permission_resolved":
                            request_id = str(data.get("requestId") or "")
                            pending = bridge.get("pending")
                            if (
                                isinstance(pending, dict)
                                and str(pending.get("requestId") or "") == request_id
                            ):
                                bridge["pending"] = None
                                _qwen_chat_bridge_write(
                                    self.root,
                                    session_id,
                                    bridge,
                                )
                            continue

                        if event_type == "turn_error":
                            message = str(
                                data.get("message")
                                or data.get("error")
                                or "Qwen Project Chat turn failed"
                            )
                            raise BackendError(
                                message,
                                session_id=session_id,
                                recovery_key="qwen:daemon-turn-error",
                            )
                        if event_type == "session_died":
                            raise BackendError(
                                str(data.get("reason") or "Qwen daemon session died"),
                                session_id=session_id,
                                recovery_key="qwen:daemon-session-died",
                            )
                        if event_type == "state_resync_required":
                            raise BackendError(
                                "Qwen daemon event replay requires resync",
                                session_id=session_id,
                                recovery_key="qwen:daemon-resync",
                            )
                        if event_type == "turn_complete":
                            text = "".join(chunks).strip()
                            if not text:
                                raise BackendError(
                                    "qwen returned an empty response",
                                    session_id=session_id,
                                )
                            return BackendResult(text, session_id)
                raise BackendError(
                    "Qwen Project Chat event stream ended before turn completion",
                    session_id=session_id,
                )
            finally:
                _qwen_chat_bridge_delete(self.root, session_id)
                try:
                    _qwen_http_json(
                        base_url,
                        f"/session/{encoded_session}",
                        method="DELETE",
                        client_id=client_id,
                        timeout=8,
                    )
                except BackendError:
                    pass


    name = "qwen"
    default_command = DEFAULT_QWEN_COMMAND
    sandbox_flags = ("-s", "--sandbox")
    supports_sandbox = True

    @classmethod
    def interaction_modes(cls) -> tuple[InteractionModeSpec, ...]:
        return (
            InteractionModeSpec("read", "plan", "Read-only analysis; no file edits or shell commands."),
            InteractionModeSpec("auto", "auto", "Classifier-approved safe actions with risky actions blocked."),
            InteractionModeSpec("yolo", "yolo", "Automatically approve all tool calls.", unsafe=True),
        )

    @classmethod
    def chat_features(cls, root: Path) -> ChatFeatureSpec:
        try:
            version = _qwen_cli_version(root)
            with _qwen_daemon_process(root) as (_, features):
                missing = sorted(_QWEN_PROJECT_CHAT_FEATURES - features)
        except BackendError as exc:
            return ChatFeatureSpec(detail=str(exc))
        version_text = ".".join(str(value) for value in version)
        if missing:
            return ChatFeatureSpec(
                detail=(
                    f"Qwen {version_text} daemon is missing the Project Chat "
                    "contract: " + ", ".join(missing)
                )
            )
        return ChatFeatureSpec(
            ask=True,
            ask_transport="daemon_permission_request",
            detail=(
                f"Qwen {version_text} advertises the native Project Chat daemon "
                "contract; ask_user_question is bridged through the session-scoped "
                "permission route."
            ),
        )

    @classmethod
    def ensure_native_session(cls, root: Path, session_id: str) -> str:
        value = str(session_id or "").strip()
        if value:
            try:
                return str(uuid.UUID(value))
            except ValueError:
                pass
        return str(uuid.uuid4())

    @classmethod
    def pending_native_ask(
        cls,
        root: Path,
        session_id: str,
    ) -> dict[str, Any] | None:
        bridge = _qwen_chat_bridge_read(root, session_id)
        if not bridge:
            return None
        pending = bridge.get("pending")
        if not isinstance(pending, dict):
            return None
        encoded_session = urllib.parse.quote(session_id, safe="")
        try:
            status, _ = _qwen_http_json_response(
                str(bridge.get("baseUrl") or ""),
                f"/session/{encoded_session}/status",
                client_id=str(bridge.get("clientId") or ""),
                timeout=1,
            )
        except BackendError:
            # The owning turn can still be alive while loopback status briefly
            # times out or reconnects. Keep the IPC record so the next poll can
            # recover the same pending permission instead of orphaning it.
            return None
        if status == 404:
            _qwen_chat_bridge_delete(root, session_id)
            return None
        if status < 200 or status >= 400:
            return None
        return pending

    @classmethod
    def resolve_native_ask(
        cls,
        root: Path,
        session_id: str,
        payload: Any,
        answers: dict[str, Any] | None,
        *,
        cancelled: bool = False,
    ) -> None:
        bridge = _qwen_chat_bridge_read(root, session_id)
        if not bridge:
            raise BackendError("Qwen Native Ask bridge is no longer active")
        current = bridge.get("pending")
        if not isinstance(current, dict):
            raise BackendError("Qwen Native Ask is no longer pending")
        request_id = str(current.get("requestId") or "")
        supplied_id = (
            str(payload.get("requestId") or "")
            if isinstance(payload, dict)
            else ""
        )
        if not request_id or (supplied_id and supplied_id != request_id):
            raise BackendError("Qwen Native Ask request no longer matches")
        response = cls.encode_ask_response(
            current,
            answers,
            cancelled=cancelled,
        )
        base_url = str(bridge.get("baseUrl") or "")
        client_id = str(bridge.get("clientId") or "")
        encoded_session = urllib.parse.quote(session_id, safe="")
        encoded_request = urllib.parse.quote(request_id, safe="")
        _qwen_http_json(
            base_url,
            f"/session/{encoded_session}/permission/{encoded_request}",
            method="POST",
            body=response,
            client_id=client_id,
            timeout=30,
        )
        bridge["pending"] = None
        _qwen_chat_bridge_write(root, session_id, bridge)

    @classmethod
    def normalize_ask_request(cls, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise BackendError("Qwen Ask payload must be an object")
        tool_call = payload.get("toolCall")
        raw = tool_call.get("rawInput") if isinstance(tool_call, dict) else None
        meta = tool_call.get("_meta") if isinstance(tool_call, dict) else None
        if (
            isinstance(meta, dict)
            and isinstance(meta.get("qwenQuestions"), list)
            and (
                not isinstance(raw, dict)
                or not isinstance(raw.get("questions"), list)
            )
        ):
            raw = {"questions": meta["qwenQuestions"]}
        if not isinstance(raw, dict):
            raw = payload.get("rawInput")
        if not isinstance(raw, dict):
            raw = payload
        questions = raw.get("questions")
        if not isinstance(questions, list) or not questions:
            raise BackendError("Qwen Ask payload is missing questions")
        result: list[dict[str, Any]] = []
        for index, question in enumerate(questions):
            if not isinstance(question, dict):
                raise BackendError("Qwen Ask question must be an object")
            options = question.get("options")
            rows: list[dict[str, str]] = []
            if isinstance(options, list):
                for option in options:
                    if not isinstance(option, dict):
                        raise BackendError("Qwen Ask option must be an object")
                    label = str(option.get("label") or "").strip()
                    if not label:
                        raise BackendError("Qwen Ask option label is required")
                    rows.append({
                        "value": label,
                        "label": label,
                        "description": str(option.get("description") or "").strip(),
                    })
            result.append({
                "id": f"q{index + 1}",
                "header": str(question.get("header") or f"Question {index + 1}"),
                "question": str(question.get("question") or ""),
                "kind": (
                    "multi_choice"
                    if rows and question.get("multiSelect") is True
                    else "choice" if rows else "text"
                ),
                "options": rows,
            })
        return result

    @classmethod
    def encode_ask_response(
        cls,
        payload: Any,
        answers: dict[str, Any] | None,
        *,
        cancelled: bool = False,
    ) -> dict[str, Any]:
        if cancelled:
            return {"outcome": {"outcome": "cancelled"}}
        if not isinstance(answers, dict):
            raise BackendError("Qwen Ask answers are required")
        questions = cls.normalize_ask_request(payload)
        encoded: dict[str, str] = {}
        for index, question in enumerate(questions):
            key = question["id"]
            if key not in answers:
                raise BackendError(f"Qwen Ask answer is missing: {key}")
            value = answers[key]
            if question["kind"] == "text":
                text = str(value or "").strip()
            elif question["kind"] == "multi_choice" and isinstance(value, dict):
                selections = [
                    str(item).strip()
                    for item in value.get("values") or []
                    if str(item).strip()
                ]
                custom = str(value.get("other") or "").strip()
                if custom:
                    selections.append(custom)
                text = ", ".join(selections)
            elif isinstance(value, dict) and str(value.get("other") or "").strip():
                text = str(value["other"]).strip()
            elif isinstance(value, dict):
                text = str(value.get("value") or "").strip()
            else:
                text = str(value or "").strip()
            if not text:
                raise BackendError(f"Qwen Ask answer is empty: {key}")
            encoded[str(index)] = text
        options = payload.get("options") if isinstance(payload, dict) else None
        option_id = ""
        if isinstance(options, list):
            allowed = [
                row for row in options
                if isinstance(row, dict)
                and str(row.get("kind") or "") not in {"reject_once", "reject"}
            ]
            preferred = next(
                (row for row in allowed if str(row.get("kind") or "") == "allow_once"),
                None,
            )
            selected = preferred or (allowed[0] if allowed else None)
            if isinstance(selected, dict):
                option_id = str(selected.get("optionId") or "")
        return {
            "outcome": {
                "outcome": "selected",
                "optionId": option_id or "proceed_once",
            },
            "answers": encoded,
        }

    @classmethod
    def configure_interaction_args(
        cls,
        mode: InteractionMode,
        extra_args: Sequence[str],
    ) -> list[str]:
        supported = {item.id: item for item in cls.interaction_modes()}
        if mode not in supported:
            raise BackendError(f"{cls.name} does not support Chat mode: {mode}")
        result: list[str] = []
        values = list(extra_args)
        index = 0
        while index < len(values):
            value = str(values[index])
            if value in {"--yolo", "-y"}:
                index += 1
                continue
            if value == "--approval-mode":
                index += 2
                continue
            if value.startswith("--approval-mode="):
                index += 1
                continue
            result.append(value)
            index += 1
        result.extend(["--approval-mode", supported[mode].native])
        return result

    @classmethod
    def discover_capabilities(cls, root: Path) -> list[CapabilitySpec]:
        commands, resources = _qwen_daemon_snapshot(root)
        return _qwen_capability_specs(commands, resources)

    @classmethod
    def reasoning_options(
        cls,
        root: Path,
        model: str,
    ) -> tuple[ReasoningOptionSpec, ...]:
        return _qwen_reasoning_options(root, model)

    @classmethod
    def available_models(cls, root: Path) -> list[str]:
        # Prefer Qwen's own live session projection: this is the same
        # configOptions model registry consumed by Qwen ACP/UI clients.
        try:
            native = _qwen_native_model_ids(root)
        except BackendError:
            native = []
        if native:
            return native

        # Older/incompatible CLI installs may not expose session_context.
        # Keep settings parsing as a bounded compatibility fallback only.
        layers = [_read_qwen_settings(path) for path in _qwen_settings_paths(root)]
        providers = _qwen_replace_setting(layers, "modelProviders")
        provider_protocol = _qwen_replace_setting(layers, "providerProtocol")
        auth_type = _qwen_selected_auth_type(layers)
        values: set[str] = set()

        for provider_id, items in providers.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                model_id = item.get("id")
                if not isinstance(model_id, str) or not model_id.strip():
                    continue
                # Match Qwen's normal Model dialog: auxiliary-only models do not
                # belong in the main model selector.
                if any(
                    item.get(flag) is True
                    for flag in (
                        "fastOnly",
                        "voiceOnly",
                        "imageOnly",
                        "visionOnly",
                    )
                ):
                    continue
                protocol = _qwen_model_protocol(
                    str(provider_id),
                    item,
                    provider_protocol,
                )
                if (
                    not protocol
                    or (protocol == "qwen-oauth" and auth_type != "qwen-oauth")
                    or (auth_type and protocol != auth_type)
                ):
                    continue
                values.add(model_id.strip())

        selected_model = _qwen_selected_model(layers)
        if selected_model:
            # Preserve the effective current/runtime model even if it is not in
            # modelProviders, matching Qwen's runtime-model behavior.
            values.add(selected_model)
        elif auth_type:
            for key in _QWEN_AUTH_MODEL_ENV_VARS[auth_type]:
                value = str(os.environ.get(key) or "").strip()
                if value:
                    values.add(value)
                    break
        return sorted(values)

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
