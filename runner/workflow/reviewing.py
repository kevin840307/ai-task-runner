"""Read-only task review flow, including adaptive no-tool finalization."""
from __future__ import annotations

from pathlib import Path

from ..agent import Agent, create_agent
from ..agent.retry import retry_model_call
from ..agent.prompts import review_finalize_prompt, review_prompt
from ..agent.results import parse_review
from ..config import RuntimeConfig
from ..errors import RunnerError
from ..engine.models import ReviewResult, RunState, Task
from ..runtime import status as runner_status
from .model_calls import readonly_structured_call


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
    task: Task,
    output: str,
) -> ReviewResult:
    """Review one changed task without changing retry or fallback semantics."""
    debug_dir = work / "debug"
    reviewer = create_agent(args, root, debug_dir, mode="review", timeout=args.planning_timeout)

    def ask_review(agent: Agent, prompt: str) -> ReviewResult:
        return readonly_structured_call(
            agent,
            prompt,
            parse_review,
            debug_dir=debug_dir,
            root=root,
            work=work,
            stage="review",
            timeout=args.planning_timeout,
            idle_timeout=args.agent_idle_after_change_timeout,
        )

    try:
        return retry_model_call(
            lambda: ask_review(
                reviewer,
                review_prompt(state, root, output),
            ),
            "AI 正在確認任務是否完成",
            task.title,
            args.retry_wait,
            args.retry_max_wait,
            1,
        )
    except RunnerError as error:
        final_error = error
        if reviewer.session_id:
            runner_status.set_status(
                "Review 異常，嘗試收斂判斷",
                f"{task.title} · reuse the same review client/session without further exploration",
            )
            try:
                return retry_model_call(
                    lambda: ask_review(reviewer, review_finalize_prompt(root)),
                    "AI 正在收斂 Review 判斷",
                    task.title,
                    args.retry_wait,
                    args.retry_max_wait,
                    1,
                )
            except RunnerError as finalize_error:
                final_error = finalize_error

        reason = str(final_error)[-1000:]
        runner_status.set_status(
            "Review 異常，暫時跳過",
            f"{task.title} · final validator will decide",
        )
        return skipped_review(reason)


__all__ = ["review_task", "skipped_review"]
