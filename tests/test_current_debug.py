from pathlib import Path

from runner.agent import AgentClient
from runner.backends.base import BackendError, BackendResult
from runner.debug import begin_model_call, note_parse_error
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


def test_current_and_last_prompt_result_follow_call_lifecycle(tmp_path, monkeypatch):
    backend = FakeBackend(tmp_path)
    client = _client(tmp_path, monkeypatch, backend)
    debug = tmp_path / ".ai-task-runner" / "debug"

    client.ask("first prompt")
    first_last_prompt = (debug / "last-prompt.txt").read_text(encoding="utf-8")
    first_last_result = (debug / "last-result.txt").read_text(encoding="utf-8")

    begin_model_call(
        debug,
        backend="fake",
        cwd=tmp_path,
        session_id="session-1",
        prompt="second prompt still running",
    )

    current = (debug / "current-prompt.txt").read_text(encoding="utf-8")
    assert "second prompt still running" in current
    assert (debug / "last-prompt.txt").read_text(encoding="utf-8") == first_last_prompt
    assert (debug / "last-result.txt").read_text(encoding="utf-8") == first_last_result


def test_completed_call_updates_matching_last_prompt_and_result(tmp_path, monkeypatch):
    backend = FakeBackend(tmp_path)
    client = _client(tmp_path, monkeypatch, backend)
    client.ask("first prompt")
    client.session_id = ""
    client.ask("second prompt")

    debug = tmp_path / ".ai-task-runner" / "debug"
    current = (debug / "current-prompt.txt").read_text(encoding="utf-8")
    last_prompt = (debug / "last-prompt.txt").read_text(encoding="utf-8")
    last_result = (debug / "last-result.txt").read_text(encoding="utf-8")

    assert "second prompt" in current and "first prompt" not in current
    assert "second prompt" in last_prompt and "first prompt" not in last_prompt
    assert '"title":"result-2"' in last_result
    assert '"title":"result-1"' not in last_result
    assert "status=completed" in last_prompt
    assert "status=completed" in last_result


def test_parse_error_is_attached_without_losing_last_result(tmp_path, monkeypatch):
    backend = FakeBackend(tmp_path)
    client = _client(tmp_path, monkeypatch, backend)
    client.ask("plan")

    debug = tmp_path / ".ai-task-runner" / "debug"
    note_parse_error(debug, RunnerError("tasks must contain at least 6 items"))
    result = (debug / "last-result.txt").read_text(encoding="utf-8")

    assert "parse_error=tasks must contain at least 6 items" in result
    assert '"title":"result-1"' in result


def test_backend_error_updates_last_prompt_and_result(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, FailingBackend(tmp_path))

    try:
        client.ask("failing prompt")
    except RunnerError:
        pass

    debug = tmp_path / ".ai-task-runner" / "debug"
    prompt = (debug / "last-prompt.txt").read_text(encoding="utf-8")
    result = (debug / "last-result.txt").read_text(encoding="utf-8")
    assert "failing prompt" in prompt
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
    result = (debug / "last-result.txt").read_text(encoding="utf-8")

    assert "parse_error=second error" in result
    assert "parse_error=first error" not in result
    assert result.count("parse_error=") == 1
