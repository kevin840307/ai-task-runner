import sys
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from runner.agent import (
    AIClient,
    AIError,
    BackendError,
    BackendResult,
    BaseBackend,
    available_models,
    backend_names,
    chat_features,
    configure_backend_args,
    configure_model_args,
    configure_interaction_args,
    create_ai_client,
    create_backend,
    discover_capabilities,
    encode_ask_response,
    ensure_native_session,
    is_session_invalid_error,
    is_transient_service_error,
    interaction_modes,
    normalize_ask_request,
    pending_native_ask,
    reasoning_options,
    resolve_native_ask,
    sandbox_supported,
    split_command,
)
from runner.agent.backend import BACKENDS
from runner.agent.opencode import OpenCodeBackend, ensure_opencode_rules
from runner.agent.qwen import QwenBackend, ensure_qwen_rules
from runner.plugins.safety import runner_source_files

def test_backend_registry_uses_interface_and_separate_modules(tmp_path):
    assert backend_names() == ("qwen", "opencode")
    assert BACKENDS["qwen"] is QwenBackend
    assert BACKENDS["opencode"] is OpenCodeBackend
    assert issubclass(QwenBackend, BaseBackend)
    assert issubclass(OpenCodeBackend, BaseBackend)
    assert QwenBackend.__module__ == "runner.agent.qwen"
    assert OpenCodeBackend.__module__ == "runner.agent.opencode"

    qwen = create_backend("qwen", sys.executable, tmp_path, [])
    opencode = create_backend("opencode", sys.executable, tmp_path, [])

    qwen_command = qwen.build_command("prompt", "session-1")
    assert "--resume" in qwen_command
    assert qwen_command[qwen_command.index("--output-format") + 1] == "stream-json"
    assert "--session" in opencode.build_command("prompt", "session-1")
    protected = runner_source_files()
    protected_names = {path.name for path in protected}
    assert {"ai_task_runner.py", "runner"} == protected_names
    assert next(path for path in protected if path.name == "runner").is_dir()


def test_new_backend_can_supply_stage_arguments_through_the_interface(monkeypatch):
    class CustomBackend(BaseBackend):
        name = "custom"
        default_command = "custom"

        @classmethod
        def configure_args(
            cls,
            mode,
            extra_args,
            *,
            allow_project_read=False,
        ):
            return [*extra_args, f"--mode={mode}", f"--read={allow_project_read}"]

        def build_command(self, prompt, session_id):
            return []

        def decode(self, raw):
            return BackendResult(raw)

    monkeypatch.setitem(BACKENDS, CustomBackend.name, CustomBackend)

    assert configure_backend_args("custom", "planning", ["--existing"], allow_project_read=True) == [
        "--existing",
        "--mode=planning",
        "--read=True",
    ]


def test_core_has_no_backend_specific_command_logic():
    root = Path(__file__).resolve().parents[1]
    source = (root / "runner" / "workflow_runner.py").read_text(encoding="utf-8")
    assert "[\"--resume\"," not in source
    assert "[\"--session\"," not in source
    assert "--output-format" not in source
    assert 'backend == "opencode"' not in source
    assert 'backend == "qwen"' not in source
    assert 'runner.agent.qwen' not in source


def test_sandbox_arguments_are_owned_by_the_backend_adapter():
    assert sandbox_supported("qwen") is True
    assert sandbox_supported("opencode") is True
    assert configure_backend_args("qwen", "runtime", [], sandbox=True).count("-s") == 1
    assert configure_backend_args(
        "qwen",
        "runtime",
        ["--sandbox"],
        sandbox=True,
    ).count("-s") == 0


def test_session_invalid_classifier_accepts_qwen_missing_saved_session_message():
    assert is_session_invalid_error("No saved session found")
    assert is_session_invalid_error("Error: No saved session found for abc-123")


def test_transient_service_classifier_excludes_qwen_sandbox_docker_failures():
    assert is_transient_service_error("HTTP 503 Service Unavailable")
    assert is_transient_service_error("connection reset by peer")
    assert is_transient_service_error("provider overloaded; try again later")
    assert is_transient_service_error("upstream temporarily unavailable")
    assert not is_transient_service_error(
        "failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine"
    )
    assert not is_transient_service_error(
        "Failed to obtain sandbox image ghcr.io/qwenlm/qwen-code:0.21.0"
    )


def qwen_excluded_tools(args):
    return {
        args[index + 1]
        for index, value in enumerate(args[:-1])
        if value == "--exclude-tools"
    } | {
        value.split("=", 1)[1]
        for value in args
        if value.startswith("--exclude-tools=")
    }




def test_qwen_planning_read_mode_is_read_only_and_file_readable():
    args = configure_backend_args("qwen", "planning", [], allow_project_read=True)
    excluded = qwen_excluded_tools(args)

    assert "--safe-mode" in args
    assert {
        "write_file",
        "edit",
        "notebook_edit",
        "run_shell_command",
        "web_fetch",
        "agent",
    } <= excluded
    assert excluded.isdisjoint(
        {
            "read_file",
            "read_many_files",
            "list_directory",
            "glob",
            "grep_search",
            "search_file_content",
        }
    )


def test_qwen_planning_read_can_be_explicitly_disabled():
    args = configure_backend_args("qwen", "planning", [], allow_project_read=False)
    excluded = qwen_excluded_tools(args)
    assert {"read_many_files", "list_directory", "glob", "grep_search", "search_file_content"} <= excluded

def test_qwen_review_mode_is_read_only_and_project_readable():
    args = configure_backend_args("qwen", "review", [])
    excluded = qwen_excluded_tools(args)

    assert "--safe-mode" in args
    assert args[args.index("--max-tool-calls") + 1] == "-1"
    assert {
        "write_file",
        "edit",
        "notebook_edit",
        "run_shell_command",
        "tool_search",
        "todo_write",
        "web_fetch",
        "agent",
    } <= excluded
    assert excluded.isdisjoint(
        {
            "read_file",
            "read_many_files",
            "list_directory",
            "glob",
            "grep_search",
            "search_file_content",
        }
    )


def test_qwen_validation_mode_allows_commands_and_temp_script_writes():
    args = configure_backend_args("qwen", "validation", [])
    excluded = qwen_excluded_tools(args)

    assert "--yolo" in args
    assert args[args.index("--max-tool-calls") + 1] == "-1"
    assert {"run_shell_command", "write_file"}.isdisjoint(excluded)
    assert {"edit", "notebook_edit", "todo_write", "agent"} <= excluded


def test_qwen_review_mode_respects_explicit_tool_call_limit():
    args = configure_backend_args("qwen", "review", ["--max-tool-calls", "8"])

    assert args.count("--max-tool-calls") == 1
    assert args[args.index("--max-tool-calls") + 1] == "8"


def test_opencode_uses_stdin_session_json_and_auto_mode(tmp_path, monkeypatch):
    from runner.runtime.process_runner import ProcessResult

    backend = OpenCodeBackend(sys.executable, tmp_path, configure_backend_args("opencode", "runtime", []))
    captured = {}

    def fake_run(command, idle_timeout_after_change=0, change_detected=None, input_text=None):
        captured["command"] = list(command)
        captured["input_text"] = input_text
        return ProcessResult(
            '\n'.join([
                '{"type":"step_start","sessionID":"ses_1","part":{"type":"step-start"}}',
                '{"type":"text","sessionID":"ses_1","part":{"type":"text","text":"ok"}}',
                '{"type":"step_finish","sessionID":"ses_1","part":{"type":"step-finish","tokens":{"input":2,"output":1,"reasoning":0,"cache":{"read":1,"write":0}}}}',
            ]),
            0,
        )

    monkeypatch.setattr(backend, "_run", fake_run)
    prompt = "OpenCode stdin prompt\n" + ("x" * 10000)
    assert backend.ask(prompt, "ses_1").text == "ok"
    assert captured["input_text"] == prompt
    assert prompt not in captured["command"]
    assert "--session" in captured["command"]
    assert "--auto" in captured["command"]


def test_qwen_models_prefer_native_session_context(tmp_path, monkeypatch):
    import runner.agent.qwen as qwen_module

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(
        qwen_module,
        "_qwen_native_model_ids",
        lambda root: ["qwen-native-b(openai)", "qwen-native-a(openai)"],
    )

    assert available_models("qwen", project) == [
        "qwen-native-b(openai)",
        "qwen-native-a(openai)",
    ]


def test_qwen_model_projection_reads_native_config_options():
    import runner.agent.qwen as qwen_module

    context = {
        "state": {
            "configOptions": [
                {"id": "mode", "category": "mode", "currentValue": "auto"},
                {
                    "id": "model",
                    "category": "model",
                    "currentValue": "qwen-current(openai)",
                    "options": [
                        {"value": "qwen-b(openai)", "name": "Qwen B"},
                        {"value": "qwen-a(openai)", "name": "Qwen A"},
                    ],
                },
            ],
        },
    }
    assert qwen_module._qwen_model_ids_from_context(context) == [
        "qwen-a(openai)",
        "qwen-b(openai)",
        "qwen-current(openai)",
    ]


def test_opencode_models_prefer_cli_catalog(tmp_path, monkeypatch):
    from runner.runtime.process_runner import ProcessResult

    (tmp_path / "opencode.json").write_text(
        json.dumps({"model": "config/only"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runner.agent.opencode.run_process",
        lambda *args, **kwargs: ProcessResult(
            "provider/model-b\nprovider/model-a\nprovider/model-b\n",
            0,
        ),
    )

    assert available_models("opencode", tmp_path) == [
        "provider/model-a",
        "provider/model-b",
    ]


def test_opencode_models_fall_back_to_config_when_cli_discovery_fails(
    tmp_path,
    monkeypatch,
):
    from runner.runtime.process_runner import ProcessResult

    (tmp_path / "opencode.json").write_text(
        json.dumps({
            "model": "lmstudio/default-model",
            "provider": {
                "lmstudio": {
                    "models": {
                        "qwen3.5-9b": {},
                        "qwen3.5-4b": {},
                    }
                }
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runner.agent.opencode.run_process",
        lambda *args, **kwargs: ProcessResult("discovery failed", 1),
    )

    assert available_models("opencode", tmp_path) == [
        "lmstudio/default-model",
        "lmstudio/qwen3.5-4b",
        "lmstudio/qwen3.5-9b",
    ]


def test_opencode_json_parser_uses_text_events_and_error_message(tmp_path):
    backend = OpenCodeBackend(sys.executable, tmp_path, [])
    raw = '\n'.join([
        '{"type":"step_start","sessionID":"ses_2","part":{"type":"step-start"}}',
        '{"type":"tool_use","sessionID":"ses_2","part":{"type":"tool","state":{"output":"tool noise"}}}',
        '{"type":"text","sessionID":"ses_2","part":{"type":"text","text":"final answer"}}',
        '{"type":"step_finish","sessionID":"ses_2","part":{"type":"step-finish","tokens":{"input":10,"output":4,"reasoning":1,"cache":{"read":6,"write":0}}}}',
    ])
    decoded = backend.decode(raw)
    assert decoded.session_id == "ses_2"
    assert decoded.text == "final answer"
    diagnostics = backend.extract_diagnostics(backend.parse_json_events(raw))
    assert diagnostics["input_tokens"] == 10
    assert diagnostics["output_tokens"] == 4
    assert diagnostics["cache_read_input_tokens"] == 6
    assert diagnostics["total_tokens"] == 15

    error = '{"type":"error","sessionID":"ses_2","error":{"data":{"message":"provider unavailable"}}}'
    assert backend.error_output(error) == "provider unavailable"


def test_opencode_permission_policy_matches_stage_and_sandbox(tmp_path, monkeypatch):
    backend = OpenCodeBackend(sys.executable, tmp_path, [])

    backend.configure_runtime("no_tool")
    assert json.loads(backend.process_environment()["OPENCODE_CONFIG_CONTENT"])["permission"] == {"*": "deny"}

    backend.configure_runtime("planning", allow_project_read=True)
    planning = json.loads(backend.process_environment()["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert planning["*"] == "deny"
    assert planning["read"] == "allow"
    assert planning["grep"] == "allow"
    assert planning["external_directory"] == "allow"
    assert planning.get("edit", "deny") == "deny"
    assert planning.get("bash", "deny") == "deny"

    backend.configure_runtime("review", sandbox=True)
    review = json.loads(backend.process_environment()["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert review["edit"] == "deny"
    assert review["bash"] == "deny"
    assert review["external_directory"] == "deny"

    backend.configure_runtime("validation", sandbox=True)
    validation = json.loads(backend.process_environment()["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert validation["task"] == "deny"
    assert validation["external_directory"] == "deny"
    assert validation.get("bash", "allow") == "allow"
    assert validation.get("edit", "allow") == "allow"

    backend.configure_runtime("runtime", sandbox=True)
    runtime = json.loads(backend.process_environment()["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert runtime == {"external_directory": "deny", "task": "deny"}


def test_opencode_permission_policy_merges_inline_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"model":"provider/model","permission":{"webfetch":"deny"}}')
    backend = OpenCodeBackend(sys.executable, tmp_path, [])
    backend.configure_runtime("runtime", sandbox=True)
    value = json.loads(backend.process_environment()["OPENCODE_CONFIG_CONTENT"])
    assert value["model"] == "provider/model"
    assert value["permission"] == {"webfetch": "deny", "external_directory": "deny", "task": "deny"}


def test_opencode_goal_reference_matches_qwen_behavior(tmp_path):
    goal = tmp_path / "goal.md"
    goal.write_text("goal", encoding="utf-8")
    backend = OpenCodeBackend(sys.executable, tmp_path, [])
    backend.prepare_project()
    backend.update_goal_reference(str(goal))
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "Original requirement file:" in text
    assert goal.resolve().as_posix() in text


def test_windows_quoted_command_path_is_unwrapped():
    assert split_command('"C:\\Program Files\\Qwen\\qwen.cmd"', windows=True) == [
        "C:\\Program Files\\Qwen\\qwen.cmd"
    ]


def test_qwen_stream_json_uses_final_result_event(tmp_path):
    backend = QwenBackend(sys.executable, tmp_path, [])
    raw = "\n".join([
        '{"type":"system","session_id":"session-1"}',
        '{"type":"message","result":"intermediate"}',
        '{"type":"result","session_id":"session-1","result":"final answer"}',
    ])
    decoded = backend.decode(raw)
    assert decoded.session_id == "session-1"
    assert decoded.text == "final answer"


def test_qwen_stream_json_api_error_envelope_raises_backend_error(tmp_path, monkeypatch):
    from runner.runtime.process_runner import ProcessResult

    backend = QwenBackend(sys.executable, tmp_path, [])
    raw = "\n".join([
        '{"type":"system","session_id":"session-1"}',
        '{"type":"result","session_id":"session-1","result":"[API Error: Connection error. (cause: UND_ERR_SOCKET: other side closed)]"}',
    ])
    monkeypatch.setattr(
        backend,
        "_run",
        lambda *args, **kwargs: ProcessResult(raw, 0),
    )

    with pytest.raises(BackendError, match="UND_ERR_SOCKET") as captured:
        backend.ask("x", session_id="session-1")

    error = captured.value
    assert error.session_id == "session-1"
    assert error.recovery_key == "qwen:api-error-envelope"
    assert error.diagnostics["api_error_envelope"] is True


def test_ai_client_marks_qwen_api_error_envelope_transient(tmp_path, monkeypatch):
    from runner.runtime.process_runner import ProcessResult

    client = AIClient("qwen", sys.executable, tmp_path, [])
    client.session_id = "session-1"
    raw = "\n".join([
        '{"type":"system","session_id":"session-1"}',
        '{"type":"result","session_id":"session-1","result":"[API Error: Connection error. (cause: UND_ERR_SOCKET: other side closed)]"}',
    ])
    monkeypatch.setattr(
        client._backend,
        "_run",
        lambda *args, **kwargs: ProcessResult(raw, 0),
    )

    with pytest.raises(AIError, match="UND_ERR_SOCKET") as captured:
        client.ask("x")

    assert captured.value.transient is True
    assert captured.value.recovery_key == "qwen:api-error-envelope"
    assert client.session_id == "session-1"


def test_qwen_stream_json_summarizes_error_output(tmp_path):
    backend = QwenBackend(sys.executable, tmp_path, [])
    raw = "\n".join([
        '{"type":"system","session_id":"session-1"}',
        '{"type":"result","session_id":"session-1","error":{"message":"Loop detection halted the run"}}',
    ])

    assert backend.error_output(raw) == "Loop detection halted the run"


def test_qwen_stream_json_error_output_falls_back_to_assistant_text(tmp_path):
    backend = QwenBackend(sys.executable, tmp_path, [])
    raw = "\n".join([
        '{"type":"system","session_id":"session-1"}',
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"last useful note"}]}}',
    ])

    assert backend.error_output(raw) == "last useful note"


def test_backend_project_rules_use_current_root_files(tmp_path):
    qwen_rule = ensure_qwen_rules(tmp_path)
    opencode_rule = ensure_opencode_rules(tmp_path)

    assert qwen_rule == tmp_path / "QWEN.md"
    assert opencode_rule == tmp_path / "AGENTS.md"
    assert not (tmp_path / ".qwen" / "QWEN.md").exists()
    assert "AI Task Runner Rules" in qwen_rule.read_text(encoding="utf-8")
    assert "AI Task Runner Rules" in opencode_rule.read_text(encoding="utf-8")


def test_backend_rejects_empty_success_output(tmp_path):
    class EmptyBackend(BaseBackend):
        name = "empty"
        default_command = sys.executable

        def build_command(self, prompt, session_id):
            return [sys.executable, "-c", "pass"]

        def decode(self, raw):
            return BackendResult(raw)

    backend = EmptyBackend(sys.executable, tmp_path, [])
    with pytest.raises(BackendError, match="empty response"):
        backend.ask("x")


def test_backend_timeout_kills_call_and_raises_recoverable_error(tmp_path):
    class SlowBackend(BaseBackend):
        name = "slow"
        default_command = sys.executable

        def build_command(self, prompt, session_id):
            return [sys.executable, "-c", "import time; time.sleep(30)"]

        def decode(self, raw):
            return BackendResult(raw)

    backend = SlowBackend(sys.executable, tmp_path, [], timeout=1)
    with pytest.raises(BackendError, match="timed out after 1 seconds") as captured:
        backend.ask("x")
    assert captured.value.recovery_key == "slow:timeout:1"




def test_ai_client_preserves_backend_recovery_key(tmp_path, monkeypatch):
    client = AIClient("qwen", sys.executable, tmp_path, [], timeout=1)

    def fail(*args, **kwargs):
        raise BackendError(
            "qwen timed out after 1 seconds:\nContainerName (regular): dynamic-99",
            recovery_key="qwen:timeout:1",
        )

    monkeypatch.setattr(client._backend, "ask", fail)
    with pytest.raises(AIError) as captured:
        client.ask("x")
    assert captured.value.recovery_key == "qwen:timeout:1"

def test_zero_backend_timeout_disables_limit(tmp_path):
    class FastBackend(BaseBackend):
        name = "fast"
        default_command = sys.executable

        def build_command(self, prompt, session_id):
            return [sys.executable, "-c", "print('ok')"]

        def decode(self, raw):
            return BackendResult(raw)

    backend = FastBackend(sys.executable, tmp_path, [], timeout=0)
    assert backend.ask("x").text.strip() == "ok"


def test_backend_error_preserves_failure_diagnostics(tmp_path):
    class FailingBackend(BaseBackend):
        name = "failing"
        default_command = sys.executable

        def build_command(self, prompt, session_id):
            code = (
                'import sys; '
                'print(\'{"type":"system","session_id":"session-9"}\'); '
                'print("raw failure detail"); '
                'raise SystemExit(7)'
            )
            return [sys.executable, "-c", code]

        def decode(self, raw):
            return BackendResult(raw)

    backend = FailingBackend(sys.executable, tmp_path, [])
    with pytest.raises(BackendError) as captured:
        backend.ask("x", session_id="old-session")

    error = captured.value
    assert error.return_code == 7
    assert error.elapsed >= 0
    assert error.command_mode == "resume"
    assert error.session_id == "session-9"
    assert error.session_source_event == "event[0]:system"
    assert "raw failure detail" in error.output


def test_backend_project_instructions_are_replaced_from_policy(tmp_path):
    policy = tmp_path / ".ai-task-runner.yaml"
    policy.write_text(
        "instructions:\n  project: |\n    First project rule.\n",
        encoding="utf-8",
    )

    path = ensure_qwen_rules(tmp_path)
    first = path.read_text(encoding="utf-8")
    assert "First project rule." in first
    assert first.count("AI-TASK-RUNNER:PROJECT-INSTRUCTIONS") == 2

    policy.write_text(
        "instructions:\n  project: |\n    Replacement project rule.\n",
        encoding="utf-8",
    )
    ensure_qwen_rules(tmp_path)
    second = path.read_text(encoding="utf-8")
    assert "First project rule." not in second
    assert "Replacement project rule." in second
    assert second.count("AI-TASK-RUNNER:PROJECT-INSTRUCTIONS") == 2

    policy.write_text("instructions:\n  project: \"\"\n", encoding="utf-8")
    ensure_qwen_rules(tmp_path)
    cleared = path.read_text(encoding="utf-8")
    assert "Replacement project rule." not in cleared
    assert "AI-TASK-RUNNER:PROJECT-INSTRUCTIONS" not in cleared


def test_qwen_ask_passes_exact_prompt_through_stdin_only(tmp_path, monkeypatch):
    from runner.runtime.process_runner import ProcessResult

    backend = QwenBackend(sys.executable, tmp_path, [])
    captured = {}

    def fake_run(command, idle_timeout_after_change=0, change_detected=None, input_text=None):
        captured["command"] = list(command)
        captured["input_text"] = input_text
        return ProcessResult(
            '{"type":"result","session_id":"s1","result":"ok"}',
            0,
        )

    monkeypatch.setattr(backend, "_run", fake_run)
    prompt = "Plan the work\nReturn JSON only\nTask count must be at least 6"
    assert backend.ask(prompt).text == "ok"

    assert "-p" not in captured["command"]
    assert captured["input_text"] == prompt


def test_qwen_long_todo_split_prompt_uses_exact_stdin(tmp_path):

    prompt = "\n".join(
        ["Plan only the remaining work. Return JSON only."]
        + [
            f"Requirement {i}: split this into one focused, independently actionable TODO."
            for i in range(1, 131)
        ]
        + [
            '{"tasks":[{"title":"Task 1","description":"Do work",'
            '"deliverable":"result","acceptance_criteria":["passes"]}]}'
        ]
    )
    backend = QwenBackend(
        sys.executable,
        tmp_path,
        configure_backend_args("qwen", "no_tool", []),
    )

    for session_id in ("", "session-123"):
        command = backend.build_command(prompt, session_id)
        assert "-p" not in command
        assert backend.stdin_prompt(prompt) == prompt
        assert "Requirement 130:" in backend.stdin_prompt(prompt)
        assert '"tasks"' in backend.stdin_prompt(prompt)
        if session_id:
            assert command[command.index("--resume") + 1] == session_id


def test_qwen_rejects_blank_stdin_prompt(tmp_path):
    backend = QwenBackend(sys.executable, tmp_path, [])
    with pytest.raises(BackendError, match="prompt is empty"):
        backend.build_command(" \n\t ", "")


def test_run_process_sends_multiline_unicode_stdin_exactly(tmp_path):
    from runner.runtime.process_runner import run_process

    prompt = "第一行\n第二行 JSON: {\"tasks\":[]}\n" + ("長內容\n" * 200)
    code = "import sys; data=sys.stdin.read(); sys.stdout.write(data)"
    result = run_process([sys.executable, "-c", code], tmp_path, 10, input_text=prompt)
    assert result.return_code == 0
    assert result.output == prompt


def test_run_process_watchdog_sends_stdin_and_eof(tmp_path):
    from runner.runtime.process_runner import run_process

    prompt = "line1\nline2\n" * 500
    code = (
        "import sys; data=sys.stdin.read(); "
        "print('LEN=' + str(len(data))); print('EOF')"
    )
    result = run_process(
        [sys.executable, "-c", code],
        tmp_path,
        10,
        idle_timeout_after_change=5,
        change_detected=lambda: False,
        input_text=prompt,
    )
    assert result.return_code == 0
    assert f"LEN={len(prompt)}" in result.output
    assert "EOF" in result.output



def test_qwen_context_snapshot_uses_display_command_only(tmp_path, monkeypatch):
    from runner.runtime.process_runner import ProcessResult
    import runner.agent.qwen as qwen_module

    backend = QwenBackend(sys.executable, tmp_path, ["--model", "local"])
    captured = {}

    def fake_run(command, cwd, timeout, *args, **kwargs):
        captured["command"] = list(command)
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        return ProcessResult(
            "## Context Usage\nModel: Qwen3.5-4B  Context window: 100.0k tokens\n",
            0,
        )

    monkeypatch.setattr(qwen_module, "run_process", fake_run)
    snapshot = backend.context_snapshot("session-123")

    assert snapshot.startswith("## Context Usage")
    assert captured["command"][:3] == [sys.executable, "-p", "/context"]
    assert captured["command"][captured["command"].index("--resume") + 1] == "session-123"
    assert "--output-format" not in captured["command"]
    assert captured["command"][-2:] == ["--model", "local"]
    assert captured["cwd"] == tmp_path
    assert captured["timeout"] <= 30


def test_qwen_context_snapshot_failure_is_text_only(tmp_path, monkeypatch):
    from runner.runtime.process_runner import ProcessResult
    import runner.agent.qwen as qwen_module

    backend = QwenBackend(sys.executable, tmp_path, [])
    monkeypatch.setattr(
        qwen_module,
        "run_process",
        lambda *args, **kwargs: ProcessResult("cannot resume", 1),
    )

    assert backend.context_snapshot("session-123") == "ERROR: /context exit 1 | cannot resume"


def test_qwen_context_usage_percent_and_fast_compression(tmp_path, monkeypatch):
    from runner.runtime.process_runner import ProcessResult
    import runner.agent.qwen as qwen_module

    backend = QwenBackend(sys.executable, tmp_path, ["--model", "local"])
    calls = []

    def fake_run(command, cwd, timeout, *args, **kwargs):
        calls.append(list(command))
        return ProcessResult("Compressed session", 0)

    monkeypatch.setattr(qwen_module, "run_process", fake_run)
    assert backend.context_usage_percent(
        "## Context Usage\nUsed 54.6k tokens (54.6%)\n"
    ) == 54.6
    assert backend.context_usage_percent("No API response yet") is None
    assert backend.compress_session("session-123") == "Compressed session"
    assert calls[0][:3] == [sys.executable, "-p", "/compress-fast"]
    assert calls[0][calls[0].index("--resume") + 1] == "session-123"


def test_opencode_runtime_permission_environment_reaches_process_runner(tmp_path, monkeypatch):
    import runner.agent.backend as base_module
    from runner.runtime.process_runner import ProcessResult

    backend = OpenCodeBackend(sys.executable, tmp_path, [])
    backend.configure_runtime("runtime", sandbox=True)
    captured = {}

    def fake_run_process(command, cwd, timeout, idle_timeout_after_change=0, change_detected=None, input_text=None, environment_overrides=None):
        captured["environment"] = environment_overrides
        return ProcessResult("ok", 0)

    monkeypatch.setattr(base_module, "run_process", fake_run_process)
    result = backend._run([sys.executable, "-c", "pass"], input_text="prompt")
    assert result.return_code == 0
    permission = json.loads(captured["environment"]["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert permission["external_directory"] == "deny"



def test_backend_adapter_owns_model_override(monkeypatch):
    assert configure_model_args(
        "qwen",
        ["--existing", "--model", "old-model", "--model=older-model"],
        "new-model",
    ) == ["--existing", "--model", "new-model"]

    class CustomBackend(BaseBackend):
        name = "custom-model"
        default_command = "custom-model"

        @classmethod
        def configure_model_args(cls, extra_args, model):
            return [*extra_args, f"--chosen-model={model}"]

        def build_command(self, prompt, session_id):
            return []

        def decode(self, raw):
            return BackendResult(raw)

    monkeypatch.setitem(BACKENDS, CustomBackend.name, CustomBackend)
    assert configure_model_args("custom-model", ["--x"], "m1") == [
        "--x",
        "--chosen-model=m1",
    ]


def test_opencode_model_override_uses_shared_backend_adapter_contract():
    args = configure_model_args(
        "opencode",
        ["--auto", "--model", "old", "--model=older"],
        "provider/new-model",
    )

    assert args == ["--auto", "--model", "provider/new-model"]


def test_future_backend_can_own_model_override_without_core_or_ui_branch(monkeypatch):
    class FutureBackend(BaseBackend):
        name = "future-agent"
        default_command = "future-agent"

        @classmethod
        def configure_model_args(cls, extra_args, model):
            return [*extra_args, f"--engine={model}"]

        def build_command(self, prompt, session_id):
            return []

        def decode(self, raw):
            return BackendResult(raw)

    monkeypatch.setitem(BACKENDS, FutureBackend.name, FutureBackend)

    assert configure_model_args("future-agent", ["--x"], "m-next") == [
        "--x",
        "--engine=m-next",
    ]


def test_ai_client_backend_override_uses_target_default_command_and_model(tmp_path):
    from runner.config.runtime import RuntimeConfig

    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.session_id = kwargs.get("session_id", "")
        def set_runtime(self, *args, **kwargs):
            captured["runtime"] = (args, kwargs)

    config = RuntimeConfig(
        backend="qwen",
        command="custom-qwen-command",
        agent_args=["--model", "global-model"],
    )
    create_ai_client(
        config,
        tmp_path,
        backend_override="opencode",
        model_override="stage-model",
        constructor=FakeClient,
    )

    assert captured["backend"] == "opencode"
    assert captured["command"] is None
    assert captured["extra_args"].count("--model") == 1
    assert captured["extra_args"][captured["extra_args"].index("--model") + 1] == "stage-model"
    assert "--auto" in captured["extra_args"]



def test_ai_client_reports_effective_model_from_backend_adapter(tmp_path, monkeypatch):
    class FakeBackend:
        name = "qwen"
        base_command = "qwen"
        root = tmp_path
        extra_args = ["--model", "stage-model"]

        def configure_runtime(self, *args, **kwargs):
            pass

    monkeypatch.setattr(
        "runner.agent.client.create_backend",
        lambda *args, **kwargs: FakeBackend(),
    )

    client = AIClient(
        backend="qwen",
        command=None,
        root=tmp_path,
        extra_args=["--model", "stage-model"],
    )

    assert client.model == "stage-model"
    client.set_extra_args(["--model", "next-model"])
    assert client.model == "next-model"


def test_backend_catalog_discovers_plugin_backends_before_listing_models(tmp_path, monkeypatch, capsys):
    import tool.backend_catalog as catalog_tool

    calls = []
    monkeypatch.setattr(
        catalog_tool,
        "discover_plugins",
        lambda: calls.append("discover"),
    )
    monkeypatch.setattr(
        catalog_tool,
        "backend_names",
        lambda: ("qwen", "plugin-backend"),
    )
    monkeypatch.setattr(
        catalog_tool,
        "available_models",
        lambda name, root: [f"{name}/model-a"],
    )

    assert catalog_tool.main([
        "--project-root", str(tmp_path),
        "--models",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert calls == ["discover"]
    assert payload["backends"] == ["qwen", "plugin-backend"]
    assert payload["models"] == {
        "qwen": ["qwen/model-a"],
        "plugin-backend": ["plugin-backend/model-a"],
    }
    assert payload["modes"]["plugin-backend"] == []


def test_qwen_models_match_main_selector_protocol_and_flags(tmp_path, monkeypatch):
    import runner.agent.qwen as qwen_module

    monkeypatch.setattr(
        qwen_module,
        "_qwen_native_model_ids",
        lambda root: (_ for _ in ()).throw(BackendError("native unavailable")),
    )
    qwen_home = tmp_path / "qwen-home"
    qwen_home.mkdir()
    (qwen_home / "settings.json").write_text(
        json.dumps({
            "security": {"auth": {"selectedType": "openai"}},
            "providerProtocol": {
                "lmstudio": "openai",
                "broken": {"unexpected": True},
            },
            "modelProviders": {
                "openai": [
                    {"id": "main"},
                    {"id": "fast", "fastOnly": True},
                    {"id": "voice", "voiceOnly": True},
                    {"id": "image", "imageOnly": True},
                    {"id": "vision", "visionOnly": True},
                    {"id": "responses", "wireApi": "responses"},
                ],
                "lmstudio": [{"id": "local-main"}],
                "anthropic": [{"id": "claude"}],
                "broken": [{"id": "broken-model"}],
                "unknown-provider": [{"id": "unknown"}],
            },
        }),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("QWEN_HOME", str(qwen_home))
    monkeypatch.setenv(
        "QWEN_CODE_SYSTEM_DEFAULTS_PATH",
        str(tmp_path / "system-defaults.json"),
    )
    monkeypatch.setenv(
        "QWEN_CODE_SYSTEM_SETTINGS_PATH",
        str(tmp_path / "system-settings.json"),
    )

    assert available_models("qwen", project) == ["local-main", "main"]


def test_backend_model_catalog_and_commands_are_adapter_owned(tmp_path, monkeypatch):
    from runner.runtime.process_runner import ProcessResult
    import runner.agent.opencode as opencode_module
    import runner.agent.qwen as qwen_module

    monkeypatch.setattr(
        qwen_module,
        "_qwen_native_model_ids",
        lambda root: (_ for _ in ()).throw(BackendError("native unavailable")),
    )

    qwen_home = tmp_path / "qwen-home"
    qwen_home.mkdir()
    (qwen_home / "settings.json").write_text(
        """{
  // user selectable models
  "security": {"auth": {"selectedType": "openai"}},
  "model": {"name": "qwen-user"},
  "modelProviders": {
    "openai": [
      {"id": "qwen-a"},
      {"id": "qwen-b"}
    ]
  }
}""",
        encoding="utf-8",
    )
    project = tmp_path / "project"
    (project / ".qwen").mkdir(parents=True)
    (project / ".qwen" / "settings.json").write_text(
        '{"modelProviders":{"openai":[{"id":"qwen-project"}]}}',
        encoding="utf-8",
    )
    system_defaults = tmp_path / "system-defaults.json"
    system_settings = tmp_path / "system-settings.json"
    monkeypatch.setenv("QWEN_HOME", str(qwen_home))
    monkeypatch.setenv("QWEN_CODE_SYSTEM_DEFAULTS_PATH", str(system_defaults))
    monkeypatch.setenv("QWEN_CODE_SYSTEM_SETTINGS_PATH", str(system_settings))
    monkeypatch.setenv("QWEN_MODEL", "qwen-env")

    # Project modelProviders replaces the lower-precedence user catalog. A
    # settings-selected model also outranks the environment model.
    assert available_models("qwen", project) == [
        "qwen-project",
        "qwen-user",
    ]

    # System settings have the highest settings-file precedence.
    system_settings.write_text(
        '{"model":{"name":"qwen-system-current"},"modelProviders":{"openai":[{"id":"qwen-system"}]}}',
        encoding="utf-8",
    )
    assert available_models("qwen", project) == [
        "qwen-system",
        "qwen-system-current",
    ]

    monkeypatch.setattr(
        opencode_module,
        "run_process",
        lambda *args, **kwargs: ProcessResult(
            "provider/model-b\nprovider/model-a\nprovider/model-b\n",
            0,
        ),
    )
    assert available_models("opencode", project) == [
        "provider/model-a",
        "provider/model-b",
    ]

    qwen = QwenBackend(
        sys.executable,
        project,
        configure_model_args("qwen", [], "qwen-project"),
    )
    qwen_command = qwen.build_command("prompt", "")
    assert qwen_command[qwen_command.index("--model") + 1] == "qwen-project"

    opencode = OpenCodeBackend(
        sys.executable,
        project,
        configure_model_args("opencode", ["--auto"], "provider/model-a"),
    )
    opencode_command = opencode.build_command("prompt", "")
    assert opencode_command[opencode_command.index("--model") + 1] == "provider/model-a"



def test_qwen_chat_modes_use_native_approval_mode_without_runtime_safe_mode():
    specs = {item.id: item for item in interaction_modes("qwen")}
    assert set(specs) == {"read", "auto", "yolo"}
    assert specs["read"].native == "plan"
    assert specs["auto"].native == "auto"
    assert specs["yolo"].unsafe is True

    read = configure_interaction_args("qwen", "read", ["--yolo", "--model", "m"])
    auto = configure_interaction_args("qwen", "auto", ["--approval-mode=yolo"])
    yolo = configure_interaction_args("qwen", "yolo", [])
    assert read == ["--model", "m", "--approval-mode", "plan"]
    assert auto == ["--approval-mode", "auto"]
    assert yolo == ["--approval-mode", "yolo"]
    assert "--safe-mode" not in read


def test_opencode_chat_modes_map_to_auto_and_permission_profiles(tmp_path):
    specs = {item.id: item for item in interaction_modes("opencode")}
    assert set(specs) == {"read", "auto", "yolo"}
    assert specs["yolo"].unsafe is True

    read_args = configure_interaction_args("opencode", "read", ["--auto", "--model", "p/m"])
    auto_args = configure_interaction_args("opencode", "auto", [])
    yolo_args = configure_interaction_args("opencode", "yolo", [])
    assert read_args == ["--model", "p/m"]
    assert auto_args == ["--auto"]
    assert yolo_args == ["--auto"]

    read_backend = OpenCodeBackend(sys.executable, tmp_path, read_args)
    read_backend.configure_interaction("read")
    read_policy = json.loads(read_backend.process_environment()["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert read_policy["*"] == "deny"
    assert read_policy["read"] == "allow"
    assert read_policy["bash"] == "deny" if "bash" in read_policy else True

    auto_backend = OpenCodeBackend(sys.executable, tmp_path, auto_args)
    auto_backend.configure_interaction("auto")
    assert auto_backend.process_environment() == {}

    yolo_backend = OpenCodeBackend(sys.executable, tmp_path, yolo_args)
    yolo_backend.configure_interaction("yolo")
    yolo_policy = json.loads(yolo_backend.process_environment()["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert yolo_policy == {"*": "allow"}



def test_qwen_capabilities_use_native_daemon_projection(monkeypatch, tmp_path):
    from runner.agent.backend import CapabilitySpec
    from runner.agent import qwen as qwen_module

    monkeypatch.setattr(
        qwen_module,
        "_qwen_daemon_snapshot",
        lambda root: (
            {
                "availableCommands": [
                    {"name": "btw", "description": "Side question", "_meta": {"source": "builtin"}},
                    {"name": "ext", "description": "Extension command", "_meta": {"source": "extension"}},
                ],
                "availableSkills": ["review"],
            },
            {
                "skills": {
                    "skills": [
                        {
                            "name": "review",
                            "description": "Review code",
                            "level": "project",
                            "status": "ok",
                            "userInvocable": True,
                        },
                        {
                            "name": "gated",
                            "description": "Path gated",
                            "level": "project",
                            "status": "path_mismatch",
                            "userInvocable": True,
                        },
                        {
                            "name": "hidden",
                            "description": "Hidden",
                            "level": "user",
                            "status": "ok",
                            "userInvocable": False,
                        },
                    ]
                }
            },
        ),
    )
    values = discover_capabilities("qwen", tmp_path)
    assert all(isinstance(item, CapabilitySpec) for item in values)
    assert [(item.token, item.kind, item.enabled) for item in values] == [
        ("/btw", "command", True),
        ("/ext", "command", True),
        ("/gated", "skill", False),
        ("/hidden", "skill", False),
        ("/review", "skill", True),
    ]
    by_token = {(item.token, item.kind): item for item in values}
    assert by_token[("/btw", "command")].source == "builtin"
    assert by_token[("/ext", "command")].source == "extension"
    assert by_token[("/gated", "skill")].availability == "path_mismatch"
    assert by_token[("/hidden", "skill")].user_invocable is False
    assert by_token[("/review", "skill")].source == "project"


def test_native_capability_discovery_failures_are_not_replaced_with_fake_entries(monkeypatch, tmp_path):
    from runner.agent import opencode as opencode_module
    from runner.agent import qwen as qwen_module

    def qwen_unavailable(root):
        raise BackendError("qwen native skill registry unavailable")

    monkeypatch.setattr(qwen_module, "_qwen_daemon_snapshot", qwen_unavailable)
    with pytest.raises(BackendError, match="native skill registry unavailable"):
        discover_capabilities("qwen", tmp_path)

    def opencode_unavailable(root, operation):
        raise BackendError(f"opencode {operation} unavailable")

    monkeypatch.setattr(opencode_module, "_opencode_api_payload", opencode_unavailable)
    with pytest.raises(BackendError, match="command.list unavailable"):
        discover_capabilities("opencode", tmp_path)


def test_qwen_model_discovery_failure_has_only_bounded_config_fallback(monkeypatch, tmp_path):
    from runner.agent import qwen as qwen_module

    monkeypatch.setattr(
        qwen_module,
        "_qwen_native_model_ids",
        lambda root: (_ for _ in ()).throw(BackendError("session context unavailable")),
    )
    assert available_models("qwen", tmp_path) == []


def test_opencode_capabilities_use_native_api_registry(monkeypatch, tmp_path):
    from runner.agent import opencode as opencode_module

    def fake_api(root, operation):
        if operation == "command.list":
            return [
                {"name": "review", "description": "Review changes", "source": "project"},
                {"name": "help", "description": "Help", "source": "builtin"},
            ]
        assert operation == "skill.list"
        return [
            {
                "name": "deploy",
                "description": "Deploy app",
                "metadata": {"opencode/slash": "true"},
                "permission": "ask",
            },
            {
                "name": "private",
                "description": "Private skill",
                "metadata": {},
                "permission": "allow",
                "source": "global",
            },
            {
                "name": "denied",
                "description": "Denied skill",
                "metadata": {"opencode/slash": "true"},
                "permission": "deny",
                "source": "project",
            },
        ]

    monkeypatch.setattr(opencode_module, "_opencode_api_payload", fake_api)
    values = discover_capabilities("opencode", tmp_path)
    by_token = {(item.token, item.kind): item for item in values}
    assert by_token[("/review", "command")].source == "project"
    assert by_token[("/deploy", "skill")].user_invocable is True
    assert by_token[("/deploy", "skill")].permission == "ask"
    assert by_token[("/private", "skill")].enabled is False
    assert by_token[("/private", "skill")].source == "global"
    assert by_token[("/denied", "skill")].user_invocable is True
    assert by_token[("/denied", "skill")].permission == "deny"
    assert by_token[("/denied", "skill")].enabled is False



def test_agent_native_ask_capability_is_backend_owned(monkeypatch, tmp_path):
    from runner.agent import opencode as opencode_module
    from runner.agent import qwen as qwen_module
    from runner.runtime.process_runner import ProcessResult

    monkeypatch.setattr(
        qwen_module,
        "run_process",
        lambda *args, **kwargs: ProcessResult("qwen-code 0.24.0\n", 0),
    )

    @contextmanager
    def qwen_daemon(root, *, environment=None):
        yield "http://127.0.0.1:4170", set(qwen_module._QWEN_PROJECT_CHAT_FEATURES)

    monkeypatch.setattr(qwen_module, "_qwen_daemon_process", qwen_daemon)
    qwen_features = chat_features("qwen", tmp_path)
    assert qwen_features.ask is True
    assert qwen_features.ask_transport == "daemon_permission_request"
    assert qwen_features.queue_mode == "service_fifo"
    assert "native Project Chat daemon contract" in qwen_features.detail

    @contextmanager
    def incomplete_qwen_daemon(root, *, environment=None):
        yield "http://127.0.0.1:4170", {"session_create", "session_prompt"}

    monkeypatch.setattr(
        qwen_module,
        "_qwen_daemon_process",
        incomplete_qwen_daemon,
    )
    incomplete_qwen = chat_features("qwen", tmp_path)
    assert incomplete_qwen.ask is False
    assert "missing the Project Chat contract" in incomplete_qwen.detail
    assert "session_permission_vote" in incomplete_qwen.detail

    monkeypatch.setattr(
        opencode_module,
        "_opencode_api_payload",
        lambda root, operation: [],
    )
    opencode_features = chat_features("opencode", tmp_path)
    assert opencode_features.ask is True
    assert opencode_features.ask_transport == "question_api"

    def unavailable(root, operation):
        raise BackendError("unknown operation")

    monkeypatch.setattr(opencode_module, "_opencode_api_payload", unavailable)
    unavailable_features = chat_features("opencode", tmp_path)
    assert unavailable_features.ask is False
    assert "unavailable" in unavailable_features.detail.lower()



def test_qwen_native_ask_bridge_reads_and_resolves_same_live_session(
    tmp_path: Path,
    monkeypatch,
):
    from runner.agent import qwen as qwen_module

    session_id = QwenBackend.ensure_native_session(tmp_path, "")
    assert QwenBackend.ensure_native_session(tmp_path, session_id) == session_id
    payload = {
        "requestId": "ask/request-1",
        "toolCall": {
            "kind": "ask_user_question",
            "rawInput": {
                "questions": [{
                    "header": "Approach",
                    "question": "Choose one",
                    "options": [{"label": "Safe"}],
                }],
            },
        },
        "options": [{"optionId": "allow-once", "kind": "allow_once"}],
    }
    qwen_module._qwen_chat_bridge_write(
        tmp_path,
        session_id,
        {
            "sessionId": session_id,
            "baseUrl": "http://127.0.0.1:4170",
            "clientId": "client-1",
            "pending": payload,
        },
    )
    calls = []

    def fake_http(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs))
        return {}

    monkeypatch.setattr(qwen_module, "_qwen_http_json", fake_http)
    monkeypatch.setattr(
        qwen_module,
        "_qwen_http_json_response",
        lambda *args, **kwargs: (200, {"status": "busy"}),
    )
    try:
        assert pending_native_ask("qwen", tmp_path, session_id) == payload
        resolve_native_ask(
            "qwen",
            tmp_path,
            session_id,
            payload,
            {"q1": {"value": "Safe"}},
        )
        assert pending_native_ask("qwen", tmp_path, session_id) is None
        assert calls == [(
            "http://127.0.0.1:4170",
            f"/session/{session_id}/permission/ask%2Frequest-1",
            {
                "method": "POST",
                "body": {
                    "outcome": {
                        "outcome": "selected",
                        "optionId": "allow-once",
                    },
                    "answers": {"0": "Safe"},
                },
                "client_id": "client-1",
                "timeout": 30,
            },
        )]
    finally:
        qwen_module._qwen_chat_bridge_delete(tmp_path, session_id)


def test_qwen_sse_stream_pairs_cursor_with_event_epoch(monkeypatch):
    from runner.agent import qwen as qwen_module

    captured = {}

    class Response:
        def close(self):
            captured["closed"] = True

    def fake_urlopen(request, timeout):
        captured["headers"] = {
            key.lower(): value for key, value in request.header_items()
        }
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(qwen_module.urllib.request, "urlopen", fake_urlopen)

    with qwen_module._qwen_sse_stream(
        "http://127.0.0.1:4170",
        "session-1",
        client_id="client-1",
        last_event_id=23,
        event_epoch="epoch-23",
        read_timeout=9,
    ):
        pass

    assert captured["headers"]["last-event-id"] == "23"
    assert captured["headers"]["x-qwen-event-epoch"] == "epoch-23"
    assert captured["headers"]["x-qwen-client-id"] == "client-1"
    assert captured["headers"]["accept-encoding"] == "identity"
    assert captured["headers"]["cache-control"] == "no-cache"
    assert captured["timeout"] == 9
    assert captured["closed"] is True


def test_qwen_project_chat_uses_daemon_session_and_keeps_runner_path_separate(
    tmp_path: Path,
    monkeypatch,
):
    from runner.agent import qwen as qwen_module

    session_id = QwenBackend.ensure_native_session(tmp_path, "")
    features = {
        *qwen_module._QWEN_PROJECT_CHAT_FEATURES,
        "session_scope_override",
    }
    calls = []

    @contextmanager
    def fake_daemon(root, *, environment=None):
        calls.append(("daemon", Path(root), bool(environment)))
        yield "http://127.0.0.1:4170", features

    @contextmanager
    def fake_stream(base_url, native_session, **kwargs):
        calls.append(("stream", base_url, native_session, kwargs))
        yield object()

    def fake_response(base_url, path, **kwargs):
        calls.append(("response", base_url, path, kwargs))
        return 404, {"code": "session_not_found"}

    def fake_http(base_url, path, **kwargs):
        calls.append(("http", base_url, path, kwargs))
        if path == "/session":
            return {
                "sessionId": session_id,
                "clientId": "client-1",
                "eventEpoch": "epoch-1",
            }
        if path.endswith("/status"):
            return {"lastEventId": 17}
        if path.endswith("/prompt"):
            return {
                "promptId": "prompt-1",
                "lastEventId": 17,
                "eventEpoch": "epoch-1",
            }
        return {}

    def fake_events(stream, *, deadline=0):
        assert deadline > 0
        # Official Qwen terminal correlation lives in event.data.promptId.
        # A replayed terminal from an older prompt must not finish this turn.
        yield {
            "type": "turn_complete",
            "data": {
                "promptId": "old-prompt",
                "stopReason": "end_turn",
            },
        }
        yield {
            "type": "session_update",
            "data": {
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "daemon "},
                },
            },
        }
        yield {
            "type": "session_update",
            "data": {
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "reply"},
                },
            },
        }
        yield {
            "type": "turn_complete",
            "data": {
                "promptId": "prompt-1",
                "stopReason": "end_turn",
            },
        }

    monkeypatch.setattr(qwen_module, "_qwen_daemon_process", fake_daemon)
    monkeypatch.setattr(qwen_module, "_qwen_sse_stream", fake_stream)
    monkeypatch.setattr(qwen_module, "_qwen_sse_events", fake_events)
    monkeypatch.setattr(qwen_module, "_qwen_http_json_response", fake_response)
    monkeypatch.setattr(qwen_module, "_qwen_http_json", fake_http)

    backend = QwenBackend(
        sys.executable,
        tmp_path,
        ["--model", "native-model"],
        timeout=30,
    )
    backend.configure_interaction("read")
    result = backend.ask("hello", session_id)

    assert result == BackendResult("daemon reply", session_id)
    create = next(
        row for row in calls
        if row[0] == "http" and row[2] == "/session"
    )
    assert create[3]["body"]["sessionId"] == session_id
    assert create[3]["body"]["approvalMode"] == "plan"
    assert create[3]["body"]["sessionScope"] == "thread"
    model = next(
        row for row in calls
        if row[0] == "http" and row[2].endswith("/model")
    )
    assert model[3]["body"] == {"modelId": "native-model"}
    stream = next(row for row in calls if row[0] == "stream")
    assert stream[3]["last_event_id"] == 17
    assert stream[3]["event_epoch"] == "epoch-1"
    assert not qwen_module._qwen_chat_bridge_path(
        tmp_path,
        session_id,
    ).exists()

    runner_backend = QwenBackend(sys.executable, tmp_path, [])
    assert runner_backend.interaction_mode is None
    assert "--output-format" in runner_backend.build_command("runner", "")


def test_qwen_native_ask_mapping_accepts_legacy_meta_questions():
    payload = {
        "requestId": "legacy-ask",
        "toolCall": {
            "rawInput": {},
            "_meta": {
                "qwenInteractionKind": "user_question",
                "qwenQuestions": [{
                    "header": "Approach",
                    "question": "Choose one",
                    "options": [{"label": "Safe"}],
                }],
            },
        },
        "options": [{"optionId": "proceed_once", "kind": "allow_once"}],
    }

    assert normalize_ask_request("qwen", payload) == [{
        "id": "q1",
        "header": "Approach",
        "question": "Choose one",
        "kind": "choice",
        "options": [{
            "value": "Safe",
            "label": "Safe",
            "description": "",
        }],
    }]
    assert encode_ask_response(
        "qwen",
        payload,
        {"q1": {"value": "Safe"}},
    ) == {
        "outcome": {
            "outcome": "selected",
            "optionId": "proceed_once",
        },
        "answers": {"0": "Safe"},
    }


def test_qwen_native_ask_mapping_preserves_multi_select():
    payload = {
        "toolCall": {
            "kind": "ask_user_question",
            "rawInput": {
                "questions": [{
                    "header": "Features",
                    "question": "Which features?",
                    "multiSelect": True,
                    "options": [
                        {"label": "Queue", "description": "Keep queue"},
                        {"label": "Ask", "description": "Keep Ask"},
                    ],
                }],
            },
        },
        "options": [{"optionId": "proceed_once", "kind": "allow_once"}],
    }

    questions = normalize_ask_request("qwen", payload)
    assert questions[0]["kind"] == "multi_choice"
    assert encode_ask_response(
        "qwen",
        payload,
        {"q1": {"values": ["Queue", "Ask"], "other": "Tasks"}},
    ) == {
        "outcome": {
            "outcome": "selected",
            "optionId": "proceed_once",
        },
        "answers": {"0": "Queue, Ask, Tasks"},
    }


def test_qwen_native_ask_mapping_round_trip():
    payload = {
        "toolCall": {
            "kind": "ask_user_question",
            "rawInput": {
                "questions": [
                    {
                        "header": "Approach",
                        "question": "Choose one",
                        "options": [
                            {"label": "Safe", "description": "Narrow"},
                            {"label": "Clean", "description": "Broad"},
                        ],
                    },
                    {
                        "header": "Why",
                        "question": "Explain",
                        "options": [],
                    },
                ]
            },
        },
        "options": [
            {"optionId": "reject", "kind": "reject_once"},
            {"optionId": "once", "kind": "allow_once"},
        ],
    }
    questions = normalize_ask_request("qwen", payload)
    assert [item["kind"] for item in questions] == ["choice", "text"]
    assert questions[0]["options"][0]["value"] == "Safe"
    response = encode_ask_response(
        "qwen",
        payload,
        {"q1": {"value": "Safe"}, "q2": "Because it is safer"},
    )
    assert response == {
        "outcome": {"outcome": "selected", "optionId": "once"},
        "answers": {"0": "Safe", "1": "Because it is safer"},
    }
    assert encode_ask_response("qwen", payload, None, cancelled=True) == {
        "outcome": {"outcome": "cancelled"}
    }


def test_opencode_native_question_mapping_round_trip():
    payload = {
        "id": "question-1",
        "sessionID": "ses_1",
        "questions": [
            {
                "header": "Packages",
                "question": "Pick packages",
                "multiple": True,
                "options": [
                    {"label": "Core", "description": "Core only"},
                    {"label": "UI", "description": "UI package"},
                ],
            },
            {
                "header": "Reason",
                "question": "Explain",
                "options": [],
                "custom": True,
            },
        ],
    }
    questions = normalize_ask_request("opencode", payload)
    assert [item["kind"] for item in questions] == ["multi_choice", "text"]
    response = encode_ask_response(
        "opencode",
        payload,
        {
            "q1": {"values": ["Core", "UI"], "other": "Docs"},
            "q2": "Needed for release",
        },
    )
    assert response == {
        "answers": [["Core", "UI", "Docs"], ["Needed for release"]]
    }
    assert encode_ask_response("opencode", payload, None, cancelled=True) is None


def test_opencode_native_ask_transport_reuses_shared_api(monkeypatch, tmp_path):
    from runner.agent import opencode as opencode_module
    from runner.runtime.process_runner import ProcessResult

    calls = []
    responses = [
        {"data": {"id": "ses_native"}},
        {"data": [
            {"id": "q-other", "sessionID": "ses_other", "questions": []},
            {
                "id": "q-native",
                "sessionID": "ses_native",
                "questions": [{
                    "header": "Pick",
                    "question": "Choose",
                    "options": [{"label": "Safe"}],
                }],
            },
        ]},
        {"data": True},
        {"data": True},
    ]

    def fake_run(command, root, timeout, *args, **kwargs):
        calls.append(list(command))
        payload = responses.pop(0)
        return ProcessResult(json.dumps(payload), 0)

    monkeypatch.setattr(opencode_module, "run_process", fake_run)
    session_id = ensure_native_session("opencode", tmp_path, "")
    assert session_id == "ses_native"
    pending = pending_native_ask("opencode", tmp_path, session_id)
    assert pending["id"] == "q-native"

    resolve_native_ask(
        "opencode",
        tmp_path,
        session_id,
        pending,
        {"q1": {"value": "Safe"}},
    )
    resolve_native_ask(
        "opencode",
        tmp_path,
        session_id,
        pending,
        None,
        cancelled=True,
    )

    assert [Path(calls[0][0]).stem, *calls[0][1:3]] == ["opencode", "api", "session.create"]
    assert json.loads(calls[0][calls[0].index("--data") + 1])["title"] == "AI Task Runner Chat"
    assert [Path(calls[1][0]).stem, *calls[1][1:3]] == ["opencode", "api", "session.question.list"]
    assert "sessionID=ses_native" in calls[1]
    assert [Path(calls[2][0]).stem, *calls[2][1:3]] == ["opencode", "api", "session.question.reply"]
    assert "sessionID=ses_native" in calls[2]
    assert "requestID=q-native" in calls[2]
    assert json.loads(calls[2][calls[2].index("--data") + 1]) == {
        "answers": [["Safe"]]
    }
    assert [Path(calls[3][0]).stem, *calls[3][1:3]] == ["opencode", "api", "session.question.reject"]
    assert "sessionID=ses_native" in calls[3]
    assert "requestID=q-native" in calls[3]
    assert "--data" not in calls[3]


def test_opencode_native_session_preserves_existing_id(monkeypatch, tmp_path):
    from runner.agent import opencode as opencode_module

    monkeypatch.setattr(
        opencode_module,
        "run_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("existing session must not call OpenCode API")
        ),
    )
    assert ensure_native_session("opencode", tmp_path, "ses_existing") == "ses_existing"


def test_qwen_reasoning_options_follow_configured_model_capability_subset(tmp_path, monkeypatch):
    qwen_home = tmp_path / "qwen-home"
    qwen_home.mkdir()
    (qwen_home / "settings.json").write_text(
        json.dumps({
            "model": {"name": "model-a", "reasoningEffort": "high"},
            "modelProviders": {
                "openai": [{
                    "id": "model-a",
                    "capabilities": {
                        "reasoning": {
                            "efforts": ["low", "high"],
                            "defaultEffort": "low",
                        }
                    },
                }]
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("QWEN_HOME", str(qwen_home))
    values = reasoning_options("qwen", tmp_path, "model-a")
    assert [item.id for item in values] == ["low", "high"]
    assert next(item for item in values if item.default).id == "high"


def test_qwen_reasoning_options_fall_back_to_native_effort_ladder(tmp_path, monkeypatch):
    qwen_home = tmp_path / "qwen-home"
    qwen_home.mkdir()
    monkeypatch.setenv("QWEN_HOME", str(qwen_home))
    values = reasoning_options("qwen", tmp_path, "unknown-model")
    assert [item.id for item in values] == ["low", "medium", "high", "xhigh", "max"]


def test_opencode_reasoning_options_come_from_selected_model_variants(tmp_path, monkeypatch):
    from runner.agent import opencode as opencode_module

    monkeypatch.setattr(
        opencode_module,
        "_opencode_api_payload",
        lambda root, operation: [
            {
                "providerID": "openai",
                "id": "gpt-5.2",
                "variants": [
                    {"id": "low"},
                    {"id": "high", "description": "Deeper reasoning"},
                ],
            },
            {
                "providerID": "anthropic",
                "id": "claude",
                "variants": [{"id": "max"}],
            },
        ] if operation == "model.list" else [],
    )
    values = reasoning_options("opencode", tmp_path, "openai/gpt-5.2")
    assert [item.id for item in values] == ["low", "high"]
    assert values[1].native == "openai/gpt-5.2#high"
    assert values[1].description == "Deeper reasoning"
    assert reasoning_options("opencode", tmp_path, "openai/missing") == ()



def test_opencode_configure_reasoning_applies_native_model_variant(tmp_path, monkeypatch):
    from runner.agent import opencode as opencode_module

    monkeypatch.setattr(
        opencode_module,
        "_opencode_api_payload",
        lambda root, operation: [{
            "providerID": "openai",
            "id": "gpt-5.2",
            "variants": [{"id": "low"}, {"id": "deep"}],
        }] if operation == "model.list" else [],
    )
    backend = OpenCodeBackend(
        sys.executable,
        tmp_path,
        ["--model", "openai/gpt-5.2"],
    )
    backend.configure_reasoning("deep")
    assert backend.reasoning == "deep"
    assert backend.model_from_args(backend.extra_args) == "openai/gpt-5.2#deep"
    with pytest.raises(BackendError, match="does not support variant"):
        backend.configure_reasoning("missing")


def test_qwen_configure_reasoning_uses_temporary_system_settings_overlay(tmp_path, monkeypatch):
    qwen_home = tmp_path / "qwen-home"
    qwen_home.mkdir()
    system = tmp_path / "system-settings.json"
    system.write_text(
        json.dumps({"security": {"auth": {"selectedType": "openai"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QWEN_HOME", str(qwen_home))
    monkeypatch.setenv("QWEN_CODE_SYSTEM_SETTINGS_PATH", str(system))
    backend = QwenBackend(sys.executable, tmp_path, ["--model", "model-a"])
    backend.configure_reasoning("high")
    env = backend.process_environment()
    overlay = Path(env["QWEN_CODE_SYSTEM_SETTINGS_PATH"])
    value = json.loads(overlay.read_text(encoding="utf-8"))
    assert value["model"]["reasoningEffort"] == "high"
    assert value["security"]["auth"]["selectedType"] == "openai"
    assert overlay != system
    backend._cleanup_reasoning_settings()
    assert not overlay.exists()
    assert system.exists()
