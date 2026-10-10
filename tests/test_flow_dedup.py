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


def test_structured_output_repair_is_bounded_inside_one_stage_session():
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return "bad"

    def parse(raw):
        raise RunnerError("bad json")

    with pytest.raises(StructuredOutputError):
        structured_call("start", parse, ask, retries=2)

    # Structured repair owns parser/schema correction only. Session rotation is
    # deliberately left to StageExecutor after this bounded attempt escapes.
    assert len(calls) == 3
