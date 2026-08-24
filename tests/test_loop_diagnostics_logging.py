from runner.model.backend import ModelBackend


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

    actual = ModelBackend.extract_diagnostics(
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
    actual = ModelBackend.extract_diagnostics(
        [],
        "Loop detection halted the run (consecutive_identical_tool_calls: repeated call).",
    )
    assert actual == {"loop_type": "consecutive_identical_tool_calls"}


def test_extract_diagnostics_does_not_invent_context_usage():
    actual = ModelBackend.extract_diagnostics(
        [{"usage": {"input_tokens": 1000, "total_tokens": 1200}}],
        "backend failure",
    )
    assert actual["input_tokens"] == 1000
    assert actual["total_tokens"] == 1200
    assert "current_context_tokens" not in actual
    assert "context_ratio" not in actual


def test_agent_collects_context_snapshot_only_for_loop(tmp_path):
    from runner.model.model import ModelClient
    from runner.model.errors import ModelError
    from runner.model.errors import BackendError

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

    agent = ModelClient.__new__(ModelClient)
    agent._backend = FakeBackend()
    agent.backend = "fake"
    agent.base_command = ["fake"]
    agent.root = tmp_path
    agent.extra_args = []
    agent.session_id = ""
    agent.timeout = 10
    agent.debug_dir = None
    agent._recoverable_session_failures = 0

    try:
        agent.ask("x")
    except ModelError as error:
        cause = error.__cause__
        assert isinstance(cause, BackendError)
        assert cause.diagnostics["context_snapshot"].startswith("## Context Usage")
    else:
        raise AssertionError("expected ModelError")


def _make_agent_with_loop_backend(
    tmp_path,
    percent,
    message="fake exit 1: Loop detection halted the run",
):
    from runner.model.model import ModelClient
    from runner.model.errors import BackendError

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

    agent = ModelClient.__new__(ModelClient)
    agent._backend = FakeBackend()
    agent.backend = "fake"
    agent.base_command = ["fake"]
    agent.root = tmp_path
    agent.extra_args = []
    agent.session_id = "loop-session"
    agent.timeout = 10
    agent.debug_dir = None
    agent._recoverable_session_failures = 0
    agent.loop_context_compress = True
    agent.loop_context_compress_threshold = 50.0
    return agent


def test_loop_context_at_threshold_compresses_without_changing_error_flow(tmp_path):
    from runner.model.errors import ModelError
    agent = _make_agent_with_loop_backend(tmp_path, 50.0)
    try:
        agent.ask("x")
    except ModelError as error:
        cause = error.__cause__
        assert cause.diagnostics["context_used_percent"] == 50.0
        assert cause.diagnostics["context_compression"] == "compressed"
        assert cause.diagnostics["session_recovery_action"] == "compress_and_retry"
        assert agent._backend.compressions == ["loop-session"]
    else:
        raise AssertionError("expected ModelError")



def test_loop_context_compression_is_disabled_by_default(tmp_path):
    from runner.model.errors import ModelError
    agent = _make_agent_with_loop_backend(tmp_path, 90.0)
    agent.loop_context_compress = False
    try:
        agent.ask("x")
    except ModelError as error:
        cause = error.__cause__
        assert cause.diagnostics["context_used_percent"] == 90.0
        assert "context_compression" not in cause.diagnostics
        assert agent._backend.compressions == []
    else:
        raise AssertionError("expected ModelError")


def test_loop_context_compression_uses_configured_threshold(tmp_path):
    from runner.model.errors import ModelError
    agent = _make_agent_with_loop_backend(tmp_path, 60.0)
    agent.loop_context_compress_threshold = 70.0
    try:
        agent.ask("x")
    except ModelError as error:
        cause = error.__cause__
        assert cause.diagnostics["context_used_percent"] == 60.0
        assert "context_compression" not in cause.diagnostics
        assert agent._backend.compressions == []
    else:
        raise AssertionError("expected ModelError")

def test_loop_context_below_threshold_does_not_compress(tmp_path):
    from runner.model.errors import ModelError
    agent = _make_agent_with_loop_backend(tmp_path, 49.9)
    try:
        agent.ask("x")
    except ModelError as error:
        cause = error.__cause__
        assert cause.diagnostics["context_used_percent"] == 49.9
        assert "context_compression" not in cause.diagnostics
        assert agent._backend.compressions == []
    else:
        raise AssertionError("expected ModelError")



def test_loop_context_compression_records_decision_metadata(tmp_path):
    from runner.model.errors import ModelError

    agent = _make_agent_with_loop_backend(tmp_path, 60.0)
    agent.loop_context_compress_threshold = 50.0
    try:
        agent.ask("x")
    except ModelError as error:
        diagnostics = error.__cause__.diagnostics
        assert diagnostics["context_compress_enabled"] is True
        assert diagnostics["context_compress_threshold"] == 50.0
        assert diagnostics["context_compress_status"] == "done"
        assert "context_compress_reason" not in diagnostics
    else:
        raise AssertionError("expected ModelError")


def test_loop_context_compression_records_skip_reason(tmp_path):
    from runner.model.errors import ModelError

    agent = _make_agent_with_loop_backend(tmp_path, 60.0)
    agent.loop_context_compress_threshold = 70.0
    try:
        agent.ask("x")
    except ModelError as error:
        diagnostics = error.__cause__.diagnostics
        assert diagnostics["context_compress_status"] == "skipped"
        assert diagnostics["context_compress_reason"] == "below_threshold"
    else:
        raise AssertionError("expected ModelError")


