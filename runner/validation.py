"""Final validation helpers for Python and AI validators."""
from __future__ import annotations

import argparse
import shutil
import sys

from runner.defaults import DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD
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
from .model_call import recover_structured_output, retry_model_call
from .project_guard import readonly_ask, restore_changed, snapshot
from .process_control import run_process


def run_ai_validator(
    args: argparse.Namespace,
    root: Path,
    work: Path,
    state: RunState,
    protected: Sequence[Path],
    ui: LiveUI,
    runtime_args: Sequence[str],
    model_call_errors_before_task_retry: int,
    custom_prompt: str = "",
) -> tuple[bool, str]:
    total = getattr(args, "final_ai_validations", 1)
    configured_required = getattr(args, "final_ai_required_passes", 0)
    required = configured_required or total // 2 + 1
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
            loop_context_compress=getattr(args, "loop_context_compress", False),
            loop_context_compress_threshold=getattr(args, "loop_context_compress_threshold", DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD),
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
                    custom_prompt,
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
        passes += result["passed"] is True

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


def run_file_validator(
    path: Path,
    root: Path,
    state_file: Path,
    timeout: int,
    extra_args: Sequence[str],
    protected: Sequence[Path],
) -> tuple[bool, str]:
    file_snapshot = snapshot(protected)
    clear_validator_reports(root)
    command = [
        sys.executable,
        str(path),
        "--project-root",
        str(root),
        "--state-file",
        str(state_file),
        *extra_args,
    ]
    try:
        result = run_process(command, root, timeout)
    except OSError as error:
        restore_changed(file_snapshot)
        raise RunnerError(f"validator failed: {error}") from error

    changed = restore_changed(file_snapshot)
    changed_message = (
        "Protected file changed during validation and was restored: "
        + ", ".join(changed)
        if changed
        else ""
    )
    if result.timed_out:
        details = [
            f"validator timeout after {timeout} seconds",
            result.output[-4000:].strip(),
            changed_message,
        ]
        raise RunnerError("\n".join(item for item in details if item))
    if changed_message:
        raise RunnerError(changed_message)
    return result.return_code == 0, result.output


def clear_validator_reports(root: Path) -> None:
    reports = root / ".ai-task-runner" / "validator-reports"
    if not reports.exists() and not reports.is_symlink():
        return
    try:
        if reports.is_symlink() or reports.is_file():
            reports.unlink()
        else:
            shutil.rmtree(reports)
    except OSError as error:
        raise RunnerError(f"failed to clear validator reports: {error}") from error
