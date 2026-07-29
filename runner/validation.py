"""Final validation helpers for Python and AI validators."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .agent import AgentClient
from .errors import RunnerError
from .models import RunState
from .ui import LiveUI
from .prompting import ai_validator_prompt
from .support import (
    parse_ai_validation,
    readonly_ask,
    retry_model_call,
)


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
    validator = AgentClient(
        backend=args.backend,
        command=args.command,
        root=root,
        extra_args=runtime_args,
        session_id="",
        timeout=args.agent_timeout,
    )

    def call() -> dict[str, Any]:
        raw, protected_changed, project_changed = readonly_ask(
            validator,
            ai_validator_prompt(
                state.goal,
                root,
                protected,
                args.validator_prompt,
            ),
            root,
            work,
            protected,
        )
        changed = [*protected_changed, *project_changed]
        if changed:
            raise RunnerError(
                "AI validator modified files and they were restored: "
                + ", ".join(changed)
            )
        return parse_ai_validation(raw)

    result = retry_model_call(
        call,
        ui,
        "正在執行最終 AI 驗證",
        "new session",
        args.retry_wait,
        args.retry_max_wait,
        model_call_errors_before_task_retry,
    )
    return result["passed"] is True, format_ai_validator_output(result)


def format_ai_validator_output(result: Mapping[str, Any]) -> str:
    raw = json.dumps(result, ensure_ascii=False)
    if result.get("passed") is True:
        return raw

    reason = str(result.get("reason", "")).strip() or "AI validation failed"
    missing_items = clean_string_items(result.get("missing_items", []))
    checks_run = clean_string_items(result.get("checks_run", []))
    suggested_checks = clean_string_items(result.get("suggested_checks", []))

    lines = ["AI_VALIDATION_FAILED", f"reason: {reason}"]
    if checks_run:
        lines.append("checks_run:")
        lines.extend(f"- {item}" for item in checks_run)
    if suggested_checks:
        lines.append("suggested_checks:")
        lines.extend(f"- {item}" for item in suggested_checks)
    lines.append("raw_json:")
    lines.append(raw)
    lines.append("blocking_missing_items:")
    if missing_items:
        lines.extend(
            f"[E{index:03d}] {item}"
            for index, item in enumerate(missing_items, 1)
        )
    else:
        lines.append(f"[E001] {reason}")
    return "\n".join(lines)


def clean_string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item).strip()
        for item in value
        if str(item).strip()
    ]
