"""Shared read-only structured model call for workflow decision stages."""
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
ReadonlyAsk = Callable[..., tuple[str, list[str], list[str]]]


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
    """Run one protected decision call and correct malformed output once."""

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

    raw = ask_raw(prompt)
    return recover_structured_output(
        raw,
        lambda text: parse_with_debug(debug_dir, parser, text),
        lambda error: ask_raw(structured_output_retry_prompt(error)),
    )


__all__ = ["readonly_structured_call"]
