import pytest

from runner.ai.errors import AIError, BackendError
from runner.backends.base import BaseBackend
from runner.bootstrap import runtime_scope
from runner.config import RuntimeConfig


def _loop_error(agent, tmp_path, *, enabled=False, threshold=50.0):
    config = RuntimeConfig(
        goal="x",
        validator="ai",
        project_root=str(tmp_path),
        loop_context_compress=enabled,
        loop_context_compress_threshold=threshold,
    )
    with runtime_scope(config), pytest.raises(AIError) as caught:
        agent.ask("x")
    assert isinstance(caught.value.__cause__, BackendError)
    return caught.value.__cause__


def test_extract_loop_diagnostics_from_backend_events():
    events = [{
        "type": "result",
        "num_turns": 101,
        "usage": {
            "input_tokens": 5218221,
            "output_tokens": 136443,
            "cache_read_input_tokens": 4686739,
            "total_tokens": 5354664,
        },
        "error": {
            "message": "Loop detection halted the run (turn_tool_call_cap: limit reached)."
        },
    }]

    actual = BaseBackend.extract_diagnostics(
        events,
        "Loop detection halted the run (turn_tool_call_cap: limit reached).",
    )

    assert actual == {
        "loop_type": "turn_tool_call_cap",
        "num_turns": 101,
        "input_tokens": 5218221,
        "output_tokens": 136443,
        "cache_read_input_tokens": 4686739,
        "total_tokens": 5354664,
    }


def test_extract_identical_tool_loop_without_usage():
    actual = BaseBackend.extract_diagnostics(
        [],
        "Loop detection halted the run (consecutive_identical_tool_calls: repeated call).",
    )
    assert actual == {"loop_type": "consecutive_identical_tool_calls"}


def test_extract_diagnostics_does_not_invent_context_usage():
    actual = BaseBackend.extract_diagnostics(
        [{"usage": {"input_tokens": 1000, "total_tokens": 1200}}],
        "backend failure",
    )
    assert actual["input_tokens"] == 1000
    assert actual["total_tokens"] == 1200
    assert "current_context_tokens" not in actual
    assert "context_ratio" not in actual


def test_agent_collects_context_snapshot_only_for_loop(tmp_path):
    from runner.ai.client import AIClient

    class FakeBackend:
        name = "fake"
        base_command = ["fake"]
        root = tmp_path
        extra_args = []
        timeout = 10

        def ask(self, *args, **kwargs):
            raise BackendError(
                "fake exit 1: Loop detection halted the run",
                session_id="loop-session",
                diagnostics={"loop_type": "loop_detection"},
            )

        def context_snapshot(self, session_id):
            assert session_id == "loop-session"
            return "## Context Usage\nContext window: 100.0k tokens"

        def context_usage_percent(self, snapshot):
            return None

        def compress_session(self, session_id):
            return ""

        def decode(self, raw):
            raise AssertionError("not used")

    agent = AIClient.__new__(AIClient)
    agent._backend = FakeBackend()
    agent.backend = "fake"
    agent.base_command = ["fake"]
    agent.root = tmp_path
    agent.extra_args = []
    agent.session_id = ""
    agent.timeout = 10
    agent.debug_dir = None
    agent._recoverable_session_failures = 0

    cause = _loop_error(agent, tmp_path)
    assert cause.diagnostics["context_snapshot"].startswith("## Context Usage")


def _make_agent_with_loop_backend(
    tmp_path,
    percent,
    message="fake exit 1: Loop detection halted the run",
):
    from runner.ai.client import AIClient

    class FakeBackend:
        name = "fake"
        base_command = ["fake"]
        root = tmp_path
        extra_args = []
        timeout = 10

        def __init__(self):
            self.compressions = []
            self.snapshots = []

        def ask(self, *args, **kwargs):
            raise BackendError(
                message,
                session_id="loop-session",
                diagnostics={"loop_type": "loop_detection"},
            )

        def context_snapshot(self, session_id):
            self.snapshots.append(session_id)
            return f"## Context Usage\nUsed 50.0k tokens ({percent}%)"

        def context_usage_percent(self, snapshot):
            return percent

        def compress_session(self, session_id):
            self.compressions.append(session_id)
            return "compressed"

        def decode(self, raw):
            raise AssertionError("not used")

    agent = AIClient.__new__(AIClient)
    agent._backend = FakeBackend()
    agent.backend = "fake"
    agent.base_command = ["fake"]
    agent.root = tmp_path
    agent.extra_args = []
    agent.session_id = "loop-session"
    agent.timeout = 10
    agent.debug_dir = None
    agent._recoverable_session_failures = 0
    return agent


def test_loop_context_at_threshold_compresses_without_changing_error_flow(tmp_path):
    agent = _make_agent_with_loop_backend(tmp_path, 50.0)
    cause = _loop_error(agent, tmp_path, enabled=True)
    assert cause.diagnostics["context_used_percent"] == 50.0
    assert cause.diagnostics["context_compression"] == "compressed"
    assert cause.diagnostics["session_recovery_action"] == "compress_and_retry"
    assert agent._backend.compressions == ["loop-session"]



def test_loop_context_compression_is_disabled_by_default(tmp_path):
    agent = _make_agent_with_loop_backend(tmp_path, 90.0)
    cause = _loop_error(agent, tmp_path)
    assert cause.diagnostics["context_used_percent"] == 90.0
    assert "context_compression" not in cause.diagnostics
    assert agent._backend.compressions == []


def test_loop_context_compression_uses_configured_threshold(tmp_path):
    agent = _make_agent_with_loop_backend(tmp_path, 60.0)
    cause = _loop_error(agent, tmp_path, enabled=True, threshold=70.0)
    assert cause.diagnostics["context_used_percent"] == 60.0
    assert "context_compression" not in cause.diagnostics
    assert agent._backend.compressions == []

def test_loop_context_below_threshold_does_not_compress(tmp_path):
    agent = _make_agent_with_loop_backend(tmp_path, 49.9)
    cause = _loop_error(agent, tmp_path, enabled=True)
    assert cause.diagnostics["context_used_percent"] == 49.9
    assert "context_compression" not in cause.diagnostics
    assert agent._backend.compressions == []



def test_loop_context_compression_records_decision_metadata(tmp_path):
    agent = _make_agent_with_loop_backend(tmp_path, 60.0)
    diagnostics = _loop_error(agent, tmp_path, enabled=True).diagnostics
    assert diagnostics["context_compress_enabled"] is True
    assert diagnostics["context_compress_threshold"] == 50.0
    assert diagnostics["context_compress_status"] == "done"
    assert "context_compress_reason" not in diagnostics


def test_loop_context_compression_records_skip_reason(tmp_path):
    agent = _make_agent_with_loop_backend(tmp_path, 60.0)
    diagnostics = _loop_error(agent, tmp_path, enabled=True, threshold=70.0).diagnostics
    assert diagnostics["context_compress_status"] == "skipped"
    assert diagnostics["context_compress_reason"] == "below_threshold"

