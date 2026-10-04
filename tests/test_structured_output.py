from __future__ import annotations

import pytest

from runner.agent.structured import structured_call
from runner.errors import RunnerError, StructuredOutputError


def test_structured_call_repairs_only_parser_errors() -> None:
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return '{"ok": true}' if len(prompts) > 1 else '{"bad": true}'

    def parser(raw: str) -> str:
        if '"ok"' not in raw:
            raise RunnerError("missing ok")
        return "done"

    assert structured_call("initial", parser, ask, retries=1) == "done"
    assert len(prompts) == 2


def test_structured_call_does_not_swallow_ask_errors_during_same_session_repair() -> None:
    calls = 0

    def ask(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return '{"bad": true}'
        raise RunnerError("transport escaped")

    def parser(_raw: str) -> str:
        raise RunnerError("schema invalid")

    with pytest.raises(RunnerError, match="transport escaped"):
        structured_call("initial", parser, ask, retries=1)


def test_structured_call_does_not_swallow_fresh_ask_errors() -> None:
    def parser(_raw: str) -> str:
        raise RunnerError("schema invalid")

    def fresh_ask() -> str:
        raise RunnerError("fresh transport escaped")

    with pytest.raises(RunnerError, match="fresh transport escaped"):
        structured_call(
            "initial",
            parser,
            lambda _prompt: '{"bad": true}',
            retries=0,
            fresh_ask=fresh_ask,
            fresh_retries=1,
        )


def test_structured_call_exhaustion_is_a_structured_output_error() -> None:
    def parser(_raw: str) -> str:
        raise RunnerError("schema invalid")

    with pytest.raises(StructuredOutputError, match="schema invalid"):
        structured_call("initial", parser, lambda _prompt: '{"bad": true}', retries=0)
