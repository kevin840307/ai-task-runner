import pytest

from runner.errors import RunnerError, StructuredOutputError
from runner.ai.structured_output import structured_call
from runner.workflow.stages.executor import StageExecutor


def test_structured_call_reuses_same_ask_for_correction():
    prompts = []
    responses = iter(["bad", '{"ok":true}'])
    def ask(prompt):
        prompts.append(prompt)
        return next(responses)
    def parse(raw):
        if not raw.startswith("{"):
            raise RunnerError("bad json")
        return raw
    assert structured_call("start", parse, ask) == '{"ok":true}'
    assert len(prompts) == 2


def test_structured_fresh_recovery_exhaustion_does_not_restart_same_retry_budget():
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return "bad"

    def parse(raw):
        raise RunnerError("bad json")

    with pytest.raises(StructuredOutputError) as caught:
        structured_call(
            "start",
            parse,
            ask,
            retries=2,
            fresh_ask=lambda: ask("fresh"),
            fresh_retries=1,
        )
    assert caught.value.same_session_retry_limit == 0
    assert len(calls) == 6


def test_failure_fingerprint_is_normalized_and_deterministic():
    class Stage:
        name = "execute"
    class Task:
        id = "t1"
    class Context:
        task = Task()
    first = StageExecutor._failure_key(Stage(), Context(), RunnerError(" A \n B "))
    second = StageExecutor._failure_key(Stage(), Context(), RunnerError("A\nB"))
    assert first == second


def test_public_max_limits_remain_accepted_for_compatibility():
    from runner.api import RunRequest
    config = RunRequest(goal="g", validator="ai", max_attempts=7, max_cycles=4).to_runtime_config()
    assert config.same_session_retries == 7
    assert config.max_cycles == 4
