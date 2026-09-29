import pytest

from runner.agent import structured_call
from runner.errors import RunnerError, StructuredOutputError


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


def test_structured_fresh_recovery_is_bounded_inside_one_stage_call():
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return "bad"

    def parse(raw):
        raise RunnerError("bad json")

    with pytest.raises(StructuredOutputError):
        structured_call(
            "start",
            parse,
            ask,
            retries=2,
            fresh_ask=lambda: ask("fresh"),
            fresh_retries=1,
        )

    assert len(calls) == 6
