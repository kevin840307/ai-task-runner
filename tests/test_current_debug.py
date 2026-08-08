from pathlib import Path

from runner.agent import AgentClient
from runner.backends.base import BackendError, BackendResult
from runner.debug import note_parse_error
from runner.errors import RunnerError


class FakeBackend:
    name = "fake"
    base_command = ["fake"]

    def __init__(self, root: Path):
        self.root = root
        self.extra_args = []
        self.timeout = 30
        self.calls = 0

    def ask(self, prompt, session_id, idle_timeout_after_change, change_detected):
        self.calls += 1
        return BackendResult(
            f'{{"tasks":[{{"title":"result-{self.calls}"}}]}}',
            f"session-{self.calls}",
        )

    def prepare_project(self):
        return []

    def build_command(self, prompt, session_id):
        return ["fake"]

    def decode(self, raw):
        return BackendResult(raw)


class FailingBackend(FakeBackend):
    def ask(self, prompt, session_id, idle_timeout_after_change, change_detected):
        raise BackendError(
            "fake exit 1",
            output='{"partial":true',
            return_code=1,
        )


def _client(tmp_path: Path, monkeypatch, backend) -> AgentClient:
    import runner.agent as agent_module

    monkeypatch.setattr(agent_module, "create_backend", lambda *args, **kwargs: backend)
    return AgentClient(
        backend="qwen",
        command="fake",
        root=tmp_path,
        extra_args=[],
        debug_dir=tmp_path / ".ai-task-runner" / "debug",
    )


def test_current_prompt_and_result_are_overwritten(tmp_path, monkeypatch):
    backend = FakeBackend(tmp_path)
    client = _client(tmp_path, monkeypatch, backend)

    client.ask("first secret prompt")
    client.session_id = ""
    client.ask("second current prompt")

    debug = tmp_path / ".ai-task-runner" / "debug"
    prompt = (debug / "current-prompt.txt").read_text(encoding="utf-8")
    result = (debug / "current-result.txt").read_text(encoding="utf-8")

    assert "second current prompt" in prompt
    assert "first secret prompt" not in prompt
    assert '"title":"result-2"' in result
    assert '"title":"result-1"' not in result
    assert "status=completed" in result
    assert "prompt_chars=21" in prompt
    assert "prompt_chars=21" in result


def test_parse_error_is_attached_without_losing_result(tmp_path, monkeypatch):
    backend = FakeBackend(tmp_path)
    client = _client(tmp_path, monkeypatch, backend)
    client.ask("plan")

    debug = tmp_path / ".ai-task-runner" / "debug"
    note_parse_error(debug, RunnerError("tasks must contain at least 6 items"))
    result = (debug / "current-result.txt").read_text(encoding="utf-8")

    assert "parse_error=tasks must contain at least 6 items" in result
    assert '"title":"result-1"' in result


def test_backend_error_updates_current_result(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, FailingBackend(tmp_path))

    try:
        client.ask("failing prompt")
    except RunnerError:
        pass

    result = (
        tmp_path / ".ai-task-runner" / "debug" / "current-result.txt"
    ).read_text(encoding="utf-8")
    assert "status=error" in result
    assert "error=fake exit 1" in result
    assert '{"partial":true' in result


def test_debug_write_failure_never_breaks_model_call(tmp_path, monkeypatch):
    backend = FakeBackend(tmp_path)
    client = _client(tmp_path, monkeypatch, backend)

    def fail_write(*args, **kwargs):
        raise OSError("debug disk unavailable")

    monkeypatch.setattr(Path, "write_text", fail_write)
    assert '"title":"result-1"' in client.ask("still run")


def test_parse_error_metadata_is_replaced_not_duplicated(tmp_path, monkeypatch):
    backend = FakeBackend(tmp_path)
    client = _client(tmp_path, monkeypatch, backend)
    client.ask("plan")

    debug = tmp_path / ".ai-task-runner" / "debug"
    note_parse_error(debug, RunnerError("first error"))
    note_parse_error(debug, RunnerError("second error"))
    result = (debug / "current-result.txt").read_text(encoding="utf-8")

    assert "parse_error=second error" in result
    assert "parse_error=first error" not in result
    assert result.count("parse_error=") == 1
