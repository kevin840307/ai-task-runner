"""Shared structured model-call primitives for workflow decision stages."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar

from ..agent import AgentClient
from ..agent.calls import recover_structured_output
from ..agent.debug import parse_with_debug
from ..agent.prompts import structured_output_retry_prompt
from ..safety.project_guard import readonly_ask, require_unchanged_project

T = TypeVar("T")
AskText = Callable[[str], str]
ReadonlyAsk = Callable[..., tuple[str, list[str], list[str]]]


def structured_call(
    prompt: str,
    parser: Callable[[str], T],
    ask: AskText,
    *,
    retries: int = 1,
) -> T:
    """Ask, parse, and correct malformed structured output in the same session."""
    raw = ask(prompt)
    return recover_structured_output(
        raw,
        parser,
        lambda error: ask(structured_output_retry_prompt(error)),
        retries=retries,
    )


def readonly_structured_call(
    agent: AgentClient,
    prompt: str,
    parser: Callable[[str], T],
    *,
    debug_dir: Path,
    root: Path,
    work: Path,
    protected: Sequence[Path],
    stage: str,
    timeout: int,
    idle_timeout: float,
    ask: ReadonlyAsk = readonly_ask,
) -> T:
    """Run one protected read-only structured call with same-session correction."""

    def ask_raw(current_prompt: str) -> str:
        raw, protected_changed, project_changed = ask(
            agent,
            current_prompt,
            root,
            work,
            protected,
            timeout=timeout,
            idle_timeout=idle_timeout,
        )
        require_unchanged_project(protected_changed, project_changed, stage)
        return raw

    return structured_call(
        prompt,
        lambda text: parse_with_debug(debug_dir, parser, text),
        ask_raw,
    )


__all__ = ["readonly_structured_call", "structured_call"]
