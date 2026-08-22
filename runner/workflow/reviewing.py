"""Read-only task review flow, including adaptive no-tool finalization."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..agent import AgentClient
from ..agent.calls import recover_structured_output, retry_model_call
from ..agent.debug import parse_with_debug
from ..agent.factory import AgentFactory
from ..agent.prompts import (
    review_finalize_prompt,
    review_prompt,
    structured_output_retry_prompt,
)
from ..agent.results import parse_review
from ..config import RuntimeConfig
from ..errors import RunnerError
from ..models import ReviewResult, RunState, Task
from ..safety.project_guard import readonly_ask, require_unchanged_project
from ..ui import LiveUI


def skipped_review(reason: str) -> ReviewResult:
    """Return the canonical provisional-review result used before Final Validator."""
    return {
        "completed": True,
        "reason": reason,
        "missing_items": [],
        "review_skipped": True,
    }


def review_task(
    args: RuntimeConfig,
    root: Path,
    work: Path,
    state: RunState,
    protected: Sequence[Path],
    ui: LiveUI,
    task: Task,
    output: str,
    agent_factory: AgentFactory | None = None,
) -> ReviewResult:
    """Review one changed task without changing retry or fallback semantics."""
    debug_dir = work / "debug"
    factory = agent_factory or AgentFactory(
        args,
        root,
        debug_dir,
        constructor=AgentClient,
    )
    reviewer = factory.create(
        "review",
        timeout=args.planning_timeout,
    )

    def ask_raw(agent: AgentClient, prompt: str) -> str:
        raw, protected_changed, project_changed_during_review = readonly_ask(
            agent,
            prompt,
            root,
            work,
            protected,
            timeout=args.planning_timeout,
            idle_timeout=args.agent_idle_after_change_timeout,
        )
        require_unchanged_project(
            protected_changed,
            project_changed_during_review,
            "review",
        )
        return raw

    def ask_review(agent: AgentClient, prompt: str) -> ReviewResult:
        raw = ask_raw(agent, prompt)
        return recover_structured_output(
            raw,
            lambda text: parse_with_debug(debug_dir, parse_review, text),
            lambda error: ask_raw(
                agent, structured_output_retry_prompt(error)
            ),
        )

    try:
        return retry_model_call(
            lambda: ask_review(
                reviewer,
                review_prompt(state, root, protected, output),
            ),
            ui,
            "AI 正在確認任務是否完成",
            task.title,
            args.retry_wait,
            args.retry_max_wait,
            1,
        )
    except RunnerError as error:
        final_error = error
        if reviewer.session_id:
            ui.set(
                "Review 異常，嘗試收斂判斷",
                f"{task.title} · reuse the same review client/session without further exploration",
            )
            try:
                return retry_model_call(
                    lambda: ask_review(reviewer, review_finalize_prompt(root)),
                    ui,
                    "AI 正在收斂 Review 判斷",
                    task.title,
                    args.retry_wait,
                    args.retry_max_wait,
                    1,
                )
            except RunnerError as finalize_error:
                final_error = finalize_error

        reason = str(final_error)[-1000:]
        ui.set(
            "Review 異常，暫時跳過",
            f"{task.title} · final validator will decide",
        )
        return skipped_review(reason)


__all__ = ["review_task", "skipped_review"]
