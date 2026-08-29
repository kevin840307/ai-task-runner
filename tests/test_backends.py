import sys
import json
from pathlib import Path

import pytest

from runner.backends.registry import (
    BACKENDS,
    backend_names,
    configure_backend_args,
    create_backend,
    sandbox_supported,
)
from runner.ai.contracts import BackendResult
from runner.backends.base import BaseBackend, split_command
from runner.ai.client import AIClient
from runner.ai.errors import AIError, BackendError
from runner.backends.opencode import OpenCodeBackend, ensure_opencode_rules
from runner.backends.qwen import QwenBackend, ensure_qwen_rules
from runner.plugins.safety import runner_source_files


def test_backend_registry_uses_interface_and_separate_modules(tmp_path):
    assert backend_names() == ("qwen", "opencode")
    assert BACKENDS["qwen"] is QwenBackend
    assert BACKENDS["opencode"] is OpenCodeBackend
    assert issubclass(QwenBackend, BaseBackend)
    assert issubclass(OpenCodeBackend, BaseBackend)
    assert QwenBackend.__module__ == "runner.backends.qwen"
    assert OpenCodeBackend.__module__ == "runner.backends.opencode"

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
    source = (root / "runner" / "task_runner.py").read_text(encoding="utf-8")
    assert "[\"--resume\"," not in source
    assert "[\"--session\"," not in source
    assert "--output-format" not in source
    assert 'backend == "opencode"' not in source
    assert 'backend == "qwen"' not in source
    assert 'runner.backends.qwen' not in source


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

    backend.configure_runtime("review", sandbox=True)
    review = json.loads(backend.process_environment()["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert review["edit"] == "deny"
    assert review["bash"] == "deny"
    assert review["external_directory"] == "deny"

    backend.configure_runtime("runtime", sandbox=True)
    runtime = json.loads(backend.process_environment()["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert runtime == {"external_directory": "deny"}


def test_opencode_permission_policy_merges_inline_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"model":"provider/model","permission":{"webfetch":"deny"}}')
    backend = OpenCodeBackend(sys.executable, tmp_path, [])
    backend.configure_runtime("runtime", sandbox=True)
    value = json.loads(backend.process_environment()["OPENCODE_CONFIG_CONTENT"])
    assert value["model"] == "provider/model"
    assert value["permission"] == {"webfetch": "deny", "external_directory": "deny"}


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
    import runner.backends.qwen as qwen_module

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
    import runner.backends.qwen as qwen_module

    backend = QwenBackend(sys.executable, tmp_path, [])
    monkeypatch.setattr(
        qwen_module,
        "run_process",
        lambda *args, **kwargs: ProcessResult("cannot resume", 1),
    )

    assert backend.context_snapshot("session-123") == "ERROR: /context exit 1 | cannot resume"


def test_qwen_context_usage_percent_and_fast_compression(tmp_path, monkeypatch):
    from runner.runtime.process_runner import ProcessResult
    import runner.backends.qwen as qwen_module

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
    import runner.backends.base as base_module
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
