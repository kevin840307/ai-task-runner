"""Subprocess and cancel control for Workflow Builder."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Callable


class GenerationCancelled(RuntimeError):
    pass


StatusWriter = Callable[..., None]
ProcessKwargsFactory = Callable[[], dict[str, Any]]


def _tail(path: Path, limit: int = 12000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:].strip()
    except OSError:
        return ""


def run_runner(
    command: list[str],
    *,
    run_root: Path,
    project: Path,
    write_status: StatusWriter,
    process_kwargs: ProcessKwargsFactory,
) -> tuple[int, str]:
    """Run exactly one AI Task Runner process and support UI cancellation.

    Workflow semantic retry belongs to result edges. Stage technical retry/session
    recovery belongs to StageExecutor. This helper owns only the Builder child
    process lifetime and cancel request.
    """
    log_path = run_root / "runner.log"
    cancel_file = run_root / "cancel.request"
    write_status(
        run_root,
        "running",
        "AI is generating Workflow and Prompt draft",
        runner_log=str(log_path),
    )

    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        kwargs = process_kwargs()
        kwargs.update({"stdout": log, "stderr": subprocess.STDOUT})
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parents[1],
            **kwargs,
        )
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
    if code == 130:
        raise GenerationCancelled("Workflow generation cancelled")
    return code, _tail(log_path)


__all__ = ["GenerationCancelled", "run_runner"]
