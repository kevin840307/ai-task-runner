import sys
from pathlib import Path

import pytest

from runner.backends import BACKENDS, AgentBackend, Backend, backend_names, create_backend
from runner.backends.base import BackendError, BackendResult, split_command
from runner.backends.opencode import OpenCodeBackend, ensure_opencode_rules
from runner.backends.qwen import QwenBackend, ensure_qwen_rules, single_line_prompt
from runner.support import runner_source_files


def test_backend_registry_uses_interface_and_separate_modules(tmp_path):
    assert backend_names() == ("qwen", "opencode")
    assert BACKENDS["qwen"] is QwenBackend
    assert BACKENDS["opencode"] is OpenCodeBackend
    assert issubclass(QwenBackend, AgentBackend)
    assert issubclass(OpenCodeBackend, AgentBackend)
    assert QwenBackend.__module__ == "runner.backends.qwen"
    assert OpenCodeBackend.__module__ == "runner.backends.opencode"

    qwen = create_backend("qwen", sys.executable, tmp_path, [])
    opencode = create_backend("opencode", sys.executable, tmp_path, [])

    qwen_command = qwen.build_command("prompt", "session-1")
    assert "--resume" in qwen_command
    assert qwen_command[qwen_command.index("--output-format") + 1] == "stream-json"
    assert "--session" in opencode.build_command("prompt", "session-1")
    protected_names = {path.name for path in runner_source_files()}
    assert {
        "api.py",
        "models.py",
        "agent_args.py",
        "script_runner.py",
        "prompting.py",
        "validation.py",
        "ui.py",
        "version.py",
        "qwen.py",
        "opencode.py",
        "base.py",
    } <= protected_names


def test_core_has_no_backend_specific_command_logic():
    root = Path(__file__).resolve().parents[1]
    source = (root / "runner" / "core.py").read_text(encoding="utf-8")
    assert "[\"--resume\"," not in source
    assert "[\"--session\"," not in source
    assert "--output-format" not in source
    assert 'backend == "opencode"' not in source


def test_windows_quoted_command_path_is_unwrapped():
    assert split_command('"C:\\Program Files\\Qwen\\qwen.cmd"', windows=True) == [
        "C:\\Program Files\\Qwen\\qwen.cmd"
    ]


def test_qwen_prompt_is_single_line_for_windows_cmd():
    prompt = "Hard rules:\n- Do the task\n\nReturn only JSON"
    assert single_line_prompt(prompt) == "Hard rules: - Do the task Return only JSON"


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
    class EmptyBackend(AgentBackend):
        name = "empty"
        default_command = sys.executable

        def build_command(self, prompt, session_id):
            return [sys.executable, "-c", "pass"]

        def decode(self, raw):
            return BackendResult(raw)

    backend = EmptyBackend(sys.executable, tmp_path, [])
    with pytest.raises(BackendError, match="empty response"):
        backend.ask("x")


def test_backend_can_send_prompt_through_stdin(tmp_path):
    class StdinBackend(AgentBackend):
        name = "stdin"
        default_command = sys.executable

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.command_prompt = None

        def prompt_stdin(self, prompt):
            return prompt

        def build_command(self, prompt, session_id):
            self.command_prompt = prompt
            return [sys.executable, "-c", "import sys; print(sys.stdin.read())"]

        def decode(self, raw):
            return BackendResult(raw)

    backend = StdinBackend(sys.executable, tmp_path, [])
    assert backend.ask("hello from stdin").text.strip() == "hello from stdin"
    assert backend.command_prompt == ""


def test_backend_timeout_kills_call_and_raises_recoverable_error(tmp_path):
    class SlowBackend(AgentBackend):
        name = "slow"
        default_command = sys.executable

        def build_command(self, prompt, session_id):
            return [sys.executable, "-c", "import time; time.sleep(30)"]

        def decode(self, raw):
            return BackendResult(raw)

    backend = SlowBackend(sys.executable, tmp_path, [], timeout=1)
    with pytest.raises(BackendError, match="timed out after 1 seconds"):
        backend.ask("x")


def test_zero_backend_timeout_disables_limit(tmp_path):
    class FastBackend(AgentBackend):
        name = "fast"
        default_command = sys.executable

        def build_command(self, prompt, session_id):
            return [sys.executable, "-c", "print('ok')"]

        def decode(self, raw):
            return BackendResult(raw)

    backend = FastBackend(sys.executable, tmp_path, [], timeout=0)
    assert backend.ask("x").text.strip() == "ok"


def test_timeout_uses_existing_retry_loop(tmp_path):
    from runner.support import LiveUI, retry_model_call

    counter = tmp_path / "count.txt"

    class RetryBackend(AgentBackend):
        name = "retry-timeout"
        default_command = sys.executable

        def build_command(self, prompt, session_id):
            code = (
                "from pathlib import Path; import time; "
                f"p=Path({str(counter)!r}); "
                "n=int(p.read_text()) if p.exists() else 0; "
                "p.write_text(str(n+1)); "
                "time.sleep(30) if n == 0 else print('ok')"
            )
            return [sys.executable, "-c", code]

        def decode(self, raw):
            return BackendResult(raw)

    backend = RetryBackend(sys.executable, tmp_path, [], timeout=1)
    result = retry_model_call(
        lambda: backend.ask("x").text,
        LiveUI(human_output=False),
        "retry timeout",
        "",
        0,
        0,
    )
    assert result.strip() == "ok"
    assert counter.read_text() == "2"


def test_backend_error_preserves_failure_diagnostics(tmp_path):
    class FailingBackend(AgentBackend):
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
