"""Shared structured model-call primitives for workflow decision stages."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from ..agent import Agent
from ..agent.retry import recover_structured_output
from ..agent.debug import parse_with_debug
from ..agent.prompts import structured_output_retry_prompt
from ..runtime.execution import readonly_ask

T = TypeVar("T")
AskText = Callable[[str], str]


def structured_call(
    prompt: str,
    parser: Callable[[str], T],
    ask: AskText,
    *,
    retries: int = 1,
) -> T:
    raw = ask(prompt)
    return recover_structured_output(
        raw,
        parser,
        lambda error: ask(structured_output_retry_prompt(error)),
        retries=retries,
    )


def readonly_structured_call(
    agent: Agent,
    prompt: str,
    parser: Callable[[str], T],
    *,
    debug_dir: Path,
    root: Path,
    work: Path,
    stage: str,
    timeout: int,
    idle_timeout: float,
) -> T:
    """Run one hook-protected read-only structured call."""

    def ask_raw(current_prompt: str) -> str:
        raw, _restored = readonly_ask(
            agent,
            current_prompt,
            root,
            work,
            timeout=timeout,
            idle_timeout=idle_timeout,
        )
        return raw

    return structured_call(
        prompt,
        lambda text: parse_with_debug(debug_dir, parser, text),
        ask_raw,
    )


__all__ = ["readonly_structured_call", "structured_call"]
