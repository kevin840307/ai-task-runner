"""Final validation helpers for Python and AI validators."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .agent import AgentClient
from .debug import parse_with_debug
from .errors import RunnerError
from .models import RunState
from .ui import LiveUI
from .prompting import ai_validator_prompt, skipped_review_tasks, structured_output_retry_prompt
from .model_results import parse_ai_validation
from .support import recover_structured_output, readonly_ask, retry_model_call


def run_ai_validator(
    args: argparse.Namespace,
    root: Path,
    work: Path,
    state: RunState,
    protected: Sequence[Path],
    ui: LiveUI,
    runtime_args: Sequence[str],
    model_call_errors_before_task_retry: int,
) -> tuple[bool, str]:
    total = getattr(args, "final_ai_validations", 1)
    required = getattr(args, "final_ai_required_passes", 1)
    debug_dir = work / "debug"
    results: list[dict[str, Any]] = []
    passes = 0

    for index in range(1, total + 1):
        # A new AgentClient with an empty session guarantees an independent run.
        validator = AgentClient(
            backend=args.backend,
            command=args.command,
            root=root,
            extra_args=runtime_args,
            session_id="",
            timeout=args.agent_timeout,
            debug_dir=debug_dir,
        )

        def ask_raw(prompt: str) -> str:
            raw, protected_changed, project_changed = readonly_ask(
                validator,
                prompt,
                root,
                work,
                protected,
                timeout=args.agent_timeout,
                idle_timeout=args.agent_idle_after_change_timeout,
            )
            changed = [*protected_changed, *project_changed]
            if changed:
                raise RunnerError(
                    "AI validator modified files and they were restored: "
                    + ", ".join(changed)
                )
            return raw

        def call() -> dict[str, Any]:
            raw = ask_raw(
                ai_validator_prompt(
                    state.goal,
                    root,
                    protected,
                    args.validator_prompt,
                    skipped_review_tasks(state),
                )
            )
            return recover_structured_output(
                raw,
                lambda text: parse_with_debug(
                    debug_dir, parse_ai_validation, text
                ),
                lambda error: ask_raw(
                    structured_output_retry_prompt(error)
                ),
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
            # An unavailable validator is an abstention, not a PASS or a FAIL.
            results.append({"error": str(error)[-1000:]})
            continue

        results.append(result)
        # A concrete blocking finding is never outvoted by other PASS results.
        if result["passed"] is not True:
            return False, format_ai_validator_runs(results, required, total)
        passes += 1

    return passes >= required, format_ai_validator_runs(results, required, total)


def format_ai_validator_runs(
    results: Sequence[Mapping[str, Any]],
    required: int,
    total: int,
) -> str:
    passes = sum(result.get("passed") is True for result in results)
    explicit_fail = any(result.get("passed") is False for result in results)
    aggregate = {
        "passed": passes >= required and not explicit_fail,
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
