import sys
from pathlib import Path

import pytest

from backends import BACKENDS, AgentBackend, Backend, backend_names, create_backend
from backends.base import BackendError, BackendResult, split_command
from backends.opencode import OpenCodeBackend
from backends.qwen import QwenBackend, single_line_prompt
from runner_support import runner_source_files


def test_backend_registry_uses_interface_and_separate_modules(tmp_path):
    assert backend_names() == ("qwen", "opencode")
    assert BACKENDS["qwen"] is QwenBackend
    assert BACKENDS["opencode"] is OpenCodeBackend
    assert issubclass(QwenBackend, AgentBackend)
    assert issubclass(OpenCodeBackend, AgentBackend)
    assert QwenBackend.__module__ == "backends.qwen"
    assert OpenCodeBackend.__module__ == "backends.opencode"

    qwen = create_backend("qwen", sys.executable, tmp_path, [])
    opencode = create_backend("opencode", sys.executable, tmp_path, [])

    assert "--resume" in qwen.build_command("prompt", "session-1")
    assert "--session" in opencode.build_command("prompt", "session-1")
    protected_names = {path.name for path in runner_source_files()}
    assert {
        "runner_api.py",
        "runner_models.py",
        "version.py",
        "qwen.py",
        "opencode.py",
        "base.py",
    } <= protected_names


def test_core_has_no_backend_specific_command_logic():
    root = Path(__file__).resolve().parents[1]
    source = (root / "runner_core.py").read_text(encoding="utf-8")
    assert "[\"--resume\"," not in source
    assert "[\"--session\"," not in source
    assert "--output-format" not in source
    assert 'backend == "qwen"' not in source
    assert 'backend == "opencode"' not in source


def test_windows_quoted_command_path_is_unwrapped():
    assert split_command('"C:\\Program Files\\Qwen\\qwen.cmd"', windows=True) == [
        "C:\\Program Files\\Qwen\\qwen.cmd"
    ]


def test_qwen_prompt_is_single_line_for_windows_cmd():
    prompt = "Hard rules:\n- Do the task\n\nReturn only JSON"
    assert single_line_prompt(prompt) == "Hard rules: - Do the task Return only JSON"


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
    from runner_support import LiveUI, retry_model_call

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
