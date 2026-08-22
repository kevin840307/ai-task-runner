from runner.backends.base import BackendError
from runner.errors import diagnostic_detail
from runner.support import retry_model_call


class UI:
    def __init__(self):
        self.details = []
    def start(self, *args):
        pass
    def stop(self, *args):
        if len(args) > 1:
            self.details.append(args[1])


def test_retry_log_preserves_loop_context_diagnostics_only():
    backend = BackendError(
        "qwen exit 1: loop",
        diagnostics={
            "loop_type": "turn_tool_call_cap",
            "num_turns": 101,
            "total_tokens": 12345,
            "context_snapshot": "## Context Usage\nContext window: 100.0k tokens",
        },
    )
    ui = UI()

    def action():
        raise Exception("unexpected")

    # Wrap exactly as AgentClient does so diagnostic_error follows __cause__.
    from runner.agent import AgentError
    wrapped = AgentError("qwen exit 1: loop")
    wrapped.__cause__ = backend

    calls = 0
    def fail_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise wrapped
        return "ok"

    assert retry_model_call(fail_once, ui, "x", "", 0, 0) == "ok"
    detail = ui.details[0]
    assert "loop_type=turn_tool_call_cap" in detail
    assert "num_turns=101" in detail
    assert "total_tokens=12345" in detail
    assert "token_scope=backend_reported_not_current_context" in detail
    assert "context_snapshot=## Context Usage Context window: 100.0k tokens" in detail


def test_diagnostic_detail_without_backend_data_stays_plain():
    from runner.errors import RunnerError
    assert diagnostic_detail(RunnerError("plain failure")) == "plain failure"
