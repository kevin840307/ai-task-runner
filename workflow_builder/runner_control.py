"""Reliable subprocess control for the AI Workflow Builder.

This module intentionally owns Builder-specific retry/logging behavior so the UI
server and the Builder orchestration script stay small.  A Runner exit code 1 is
a terminal result for one Runner invocation, but generation is a temporary draft
operation, so the Builder may safely retry once with a fresh Runner state/session.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable


class GenerationCancelled(RuntimeError):
    """Raised when the Generator cancel.request is observed."""


StatusWriter = Callable[..., None]
ProcessKwargsFactory = Callable[[], dict[str, Any]]


def _tail(path: Path, limit: int = 12000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:].strip()


def _fresh_retry_command(command: list[str]) -> list[str]:
    """Return the same Runner command with a fresh state/session boundary."""
    cleaned = [arg for arg in command if arg not in {"--resume", "--force-new"}]
    return [*cleaned, "--force-new"]


def run_with_recovery(
    command: list[str],
    *,
    run_root: Path,
    project: Path,
    write_status: StatusWriter,
    process_kwargs: ProcessKwargsFactory,
    max_attempts: int = 2,
) -> tuple[int, str]:
    """Run the Builder's AI Task Runner with one bounded fresh retry.

    ai_task_runner treats exit code 1 as a completed logical failure, so its own
    crash supervisor correctly does not resume it.  For *draft generation* that
    result is recoverable at a higher boundary: keep the draft for evidence, start
    a fresh Runner state/session, and ask the Builder workflow to try again.

    Every attempt writes to ``runner-attempt-N.log`` so a final failure has useful
    diagnostics instead of only "exit code 1".
    """
    attempts = max(1, int(max_attempts))
    cancel_file = run_root / "cancel.request"
    current_command = list(command)
    last_log = ""

    for attempt in range(1, attempts + 1):
        log_path = run_root / f"runner-attempt-{attempt}.log"
        write_status(
            run_root,
            "running",
            "AI is generating Workflow and Prompt draft"
            if attempt == 1
            else f"Retrying Workflow generation with a fresh session ({attempt}/{attempts})",
            builder_attempt=attempt,
            builder_attempts=attempts,
            runner_log=str(log_path),
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            kwargs = process_kwargs()
            kwargs.update({"stdout": log, "stderr": subprocess.STDOUT})
            process = subprocess.Popen(current_command, cwd=Path(__file__).resolve().parents[1], **kwargs)
            while process.poll() is None:
                if cancel_file.exists():
                    write_status(run_root, "cancelling", "Cancelling Workflow generation…")
                    runtime = project / ".ai-task-runner"
                    runtime.mkdir(parents=True, exist_ok=True)
                    (runtime / "stop.request").write_text("stop\n", encoding="utf-8")
                    try:
                        process.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:
                            process.wait(timeout=4)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=4)
                    raise GenerationCancelled("Workflow generation cancelled")
                time.sleep(0.25)
            code = int(process.returncode or 0)

        last_log = _tail(log_path)
        if code == 0:
            return 0, last_log
        if code == 130:
            raise GenerationCancelled("Workflow generation cancelled")
        if attempt >= attempts:
            return code, last_log

        # Exit 1 is a terminal logical result for a single Runner invocation.  The
        # Generator owns a temporary workspace, so retrying from a fresh state is
        # safe and gives validation/recovery a second independent chance.
        write_status(
            run_root,
            "running",
            f"Workflow attempt {attempt} did not complete; retrying automatically",
            builder_attempt=attempt,
            builder_attempts=attempts,
            runner_exit_code=code,
            runner_log=str(log_path),
        )
        current_command = _fresh_retry_command(command)
        time.sleep(1.0)

    return 1, last_log
