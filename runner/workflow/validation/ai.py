"""Independent AI validation runs and quorum result formatting."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import partial
from pathlib import Path
from typing import Any

from ...agent import AgentClient
from ...agent.calls import retry_model_call
from ...agent.factory import AgentFactory
from ...agent.prompts import (
    ai_validator_prompt,
    skipped_review_tasks,
)
from ...agent.results import parse_ai_validation
from ...config import RuntimeConfig
from ...errors import RunnerError
from ...models import RunState
from ...safety.project_guard import readonly_ask
from ...ui import LiveUI
from ..structured import readonly_structured_call


def run_ai_validator(
    args: RuntimeConfig,
    root: Path,
    work: Path,
    state: RunState,
    protected: Sequence[Path],
    ui: LiveUI,
    model_call_errors_before_task_retry: int,
    custom_prompt: str = "",
    agent_factory: AgentFactory | None = None,
) -> tuple[bool, str]:
    total = args.final_ai_validations
    configured_required = args.final_ai_required_passes
    required = configured_required or total // 2 + 1
    debug_dir = work / "debug"
    results: list[Mapping[str, Any]] = []
    passes = 0
    factory = agent_factory or AgentFactory(
        args,
        root,
        debug_dir,
        constructor=AgentClient,
    )

    for index in range(1, total + 1):
        # Empty sessions make quorum runs independent from one another.
        validator = factory.create(
            "runtime",
            timeout=args.agent_timeout,
        )

        call = partial(
            readonly_structured_call,
            validator,
            ai_validator_prompt(
                state.goal, root, protected, custom_prompt, skipped_review_tasks(state)
            ),
            parse_ai_validation,
            debug_dir=debug_dir,
            root=root,
            work=work,
            protected=protected,
            stage="AI validator",
            timeout=args.agent_timeout,
            idle_timeout=args.agent_idle_after_change_timeout,
            ask=readonly_ask,
        )

        try:
            result = retry_model_call(
                call,
                ui,
                "正在執行最終 AI 驗證",
                f"new session · {index}/{total} · passes {passes}/{required}",
                args.retry_wait,
                args.retry_max_wait,
                model_call_errors_before_task_retry,
            )
        except RunnerError as error:
            # An unavailable validator abstains instead of passing or failing.
            results.append({"error": str(error)[-1000:]})
        else:
            results.append(result)
            passes += result["passed"] is True

        remaining = total - index
        if passes >= required or passes + remaining < required:
            break

    return passes >= required, format_ai_validator_runs(results, required, total)


def format_ai_validator_runs(
    results: Sequence[Mapping[str, Any]],
    required: int,
    total: int,
) -> str:
    required = required or total // 2 + 1
    passes = sum(result.get("passed") is True for result in results)
    aggregate = {
        "passed": passes >= required,
        "passes": passes,
        "required_passes": required,
        "configured_validations": total,
        "completed_validations": len(results),
        "validations": list(results),
    }
    if aggregate["passed"]:
        return json.dumps(aggregate, ensure_ascii=False)

    lines = [
        "AI_VALIDATION_FAILED",
        f"passes: {passes}/{required}",
        f"completed_validations: {len(results)}/{total}",
    ]
    blocking: list[str] = []
    errors: list[str] = []
    for run_index, result in enumerate(results, 1):
        if result.get("passed") is True:
            continue
        if "error" in result:
            errors.append(f"run {run_index}: {result['error']}")
            continue
        reason = str(result.get("reason", "")).strip() or "AI validation failed"
        items = clean_string_items(result.get("missing_items", [])) or [reason]
        blocking.extend(f"run {run_index}: {item}" for item in items)
    if errors:
        lines.append("validation_errors:")
        lines.extend(f"- {item}" for item in errors)
    lines.append("blocking_missing_items:")
    if blocking:
        lines.extend(
            f"[E{index:03d}] {item}" for index, item in enumerate(blocking, 1)
        )
    else:
        lines.append("[E001] insufficient independent Final AI PASS results")
    lines.append("raw_json:")
    lines.append(json.dumps(aggregate, ensure_ascii=False))
    return "\n".join(lines)


def clean_string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item).strip()
        for item in value
        if str(item).strip()
    ]


__all__ = [
    "clean_string_items",
    "format_ai_validator_runs",
    "run_ai_validator",
]
