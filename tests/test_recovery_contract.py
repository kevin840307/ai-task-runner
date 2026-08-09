from types import SimpleNamespace

from runner.agent import AgentError
from runner.errors import RunnerError
from runner.support import recover_structured_output, retry_model_call


def test_structured_output_retries_with_short_same_session_correction():
    prompts = []

    def parse(raw):
        if raw != '{"ok":true}':
            raise RunnerError("invalid JSON contract")
        return True

    result = recover_structured_output(
        "not-json",
        parse,
        lambda error: prompts.append(error) or '{"ok":true}',
    )

    assert result is True
    assert prompts == ["invalid JSON contract"]


def test_transient_service_errors_do_not_exhaust_model_error_budget():
    calls = 0
    ui = SimpleNamespace(start=lambda *a, **k: None, stop=lambda *a, **k: None)

    def action():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise AgentError("API timeout", transient=True)
        return "ok"

    assert retry_model_call(action, ui, "s", "d", 0, 0, max_errors=1) == "ok"
    assert calls == 3
