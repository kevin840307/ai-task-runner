#!/usr/bin/env python3
"""Thin CLI adapter for the shared AI Task Runner entry point."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from collections.abc import Sequence
from pathlib import Path

from runner.api import RunRequest, run
from runner.backends import backend_names
from runner.config.defaults import (
    DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_API_WAIT_TIMEOUT,
    DEFAULT_BACKEND,
    DEFAULT_FINAL_AI_REQUIRED_PASSES,
    DEFAULT_FINAL_AI_VALIDATIONS,
    DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_CYCLES,
    DEFAULT_PLANNING_TIMEOUT,
    DEFAULT_REVIEW_RETRIES,
    DEFAULT_VALIDATOR_TIMEOUT,
    DEFAULT_WATCHDOG_INTERVAL,
)
from runner.errors import ConfigurationError
from runner.runtime.process import ACTIVE_PROCESS_FILE
from runner.version import __version__


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(description="Reusable AI task runner")
    command_parser.add_argument("--goal")
    command_parser.add_argument(
        "--goal-file",
        help="UTF-8 text file containing the goal; mutually exclusive with --goal",
    )
    command_parser.add_argument("--project-root", default=".")
    command_parser.add_argument("--script", help="YAML array of prompt + validator items")
    command_parser.add_argument("--validator", help="validator.py path or literal 'ai'")
    command_parser.add_argument(
        "--validator-prompt",
        default="",
        help="extra instructions when --validator ai is used",
    )
    command_parser.add_argument(
        "--ai-validator-prompt",
        default="",
        help="optional Final AI validation instructions after a file validator passes",
    )
    command_parser.add_argument(
        "--ai-validator-prompt-file",
        help="UTF-8 file containing Final AI validation instructions; mutually exclusive with --ai-validator-prompt",
    )
    command_parser.add_argument(
        "--backend",
        choices=backend_names(),
        default=DEFAULT_BACKEND,
    )
    command_parser.add_argument("--command")
    command_parser.add_argument(
        "--sandbox",
        action="store_true",
        help="run agent calls in the backend's sandbox mode",
    )
    command_parser.add_argument("--agent-arg", action="append", default=[])
    command_parser.add_argument("--validator-arg", action="append", default=[])
    command_parser.add_argument("--protect-file", action="append", default=[])
    command_parser.add_argument(
        "--validator-timeout",
        type=int,
        default=DEFAULT_VALIDATOR_TIMEOUT,
    )
    command_parser.add_argument(
        "--agent-timeout",
        type=int,
        default=DEFAULT_AGENT_TIMEOUT,
        help="maximum seconds for one AI CLI call; 0 disables the limit",
    )
    command_parser.add_argument(
        "--planning-timeout",
        type=int,
        default=DEFAULT_PLANNING_TIMEOUT,
        help="maximum seconds for one AI planning call; 0 disables the limit",
    )
    command_parser.add_argument(
        "--agent-idle-after-change-timeout",
        type=float,
        default=DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
        help=(
            "model-call idle seconds without project changes or CLI output before "
            "stopping the AI call and letting review decide; 0 disables it"
        ),
    )
    command_parser.add_argument(
        "--api-wait-timeout",
        type=float,
        default=DEFAULT_API_WAIT_TIMEOUT,
        help="maximum seconds in one API/service retry window; the runner keeps retrying after each window",
    )
    command_parser.add_argument(
        "--watchdog-interval",
        type=float,
        default=DEFAULT_WATCHDOG_INTERVAL,
        help="seconds between watchdog checks",
    )
    command_parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help="task recovery escalation threshold; never stops the runner; 0 uses no-progress detection only",
    )
    command_parser.add_argument(
        "--review-retries",
        type=int,
        default=DEFAULT_REVIEW_RETRIES,
        help="AI Review same-session retries before skip; 0 disables skip",
    )
    command_parser.add_argument(
        "--max-cycles",
        type=int,
        default=DEFAULT_MAX_CYCLES,
        help="maximum workflow/replan cycles; 0 means unlimited (default)",
    )
    command_parser.add_argument(
        "--retry-delay",
        type=float,
        default=2,
        help="logical task retry delay",
    )
    command_parser.add_argument(
        "--retry-wait",
        type=float,
        default=5,
        help="initial model-call retry wait",
    )
    command_parser.add_argument(
        "--final-ai-validations",
        "--ai-validator-count",
        dest="final_ai_validations",
        type=int,
        default=DEFAULT_FINAL_AI_VALIDATIONS,
        help="maximum independent Final AI validation runs; each uses a fresh session",
    )
    command_parser.add_argument(
        "--final-ai-required-passes",
        type=int,
        default=DEFAULT_FINAL_AI_REQUIRED_PASSES,
        help="Final AI PASS results required; 0 uses strict majority (default)",
    )
    command_parser.add_argument(
        "--retry-max-wait",
        type=float,
        default=300,
        help="maximum model-call retry wait",
    )
    command_parser.add_argument(
        "--loop-context-compress",
        action="store_true",
        help="on Loop Detection, compact the session when current context usage reaches the configured threshold",
    )
    command_parser.add_argument(
        "--loop-context-compress-threshold",
        type=float,
        default=DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD,
        metavar="PERCENT",
        help="context usage percent required for Loop Detection compression (default: 50)",
    )
    command_parser.add_argument("--work-dir", default=".ai-task-runner")
    command_parser.add_argument(
        "--json-events",
        action="store_true",
        help="emit JSON Lines progress events",
    )
    command_parser.add_argument("--resume", action="store_true")
    command_parser.add_argument("--force-new", action="store_true")
    command_parser.add_argument(
        "--plan-only",
        action="store_true",
        help="create or refresh the TODO plan, save state, then exit before execution",
    )
    return command_parser


def main(argv: Sequence[str] | None = None) -> int:
    request = RunRequest.from_namespace(parser().parse_args(argv))
    while True:
        try:
            result = run(request)
            if request.plan_only or result.completed:
                return result.exit_code
            _continue_unfinished_run(request, result.state_files)
        except KeyboardInterrupt:
            _report_error(request, "runner.stopped", "Stopped; use --resume", 130)
            return 130
        except (ConfigurationError, ValueError) as error:
            _report_error(request, "runner.failed", str(error), 1)
            return 1
        except Exception as error:
            _recover_from_unexpected_error(request, error)



def _continue_unfinished_run(
    request: RunRequest,
    state_files: Sequence[str],
) -> None:
    """Never trust a normal return as completion unless persisted state confirms it."""
    if any(Path(path).is_file() for path in state_files):
        request.resume, request.force_new = True, False
        detail = "run returned before Final Validator completion; resuming saved state"
    else:
        request.resume, request.force_new = False, False
        detail = "run returned without completed state; continuing original request"
    _report_error(request, "runner.retry", detail, 0)
    if request.retry_delay:
        time.sleep(request.retry_delay)


def _recover_from_unexpected_error(
    request: RunRequest,
    error: BaseException,
) -> None:
    log = Path(request.project_root, request.work_dir, "exception.log").resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as file:
        file.write(
            f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
            f"{type(error).__name__}: {error}\n{traceback.format_exc()}"
        )

    state_file = Path(request.project_root, request.work_dir, "state.json").resolve()
    if state_file.is_file():
        request.resume, request.force_new = True, False
        detail = f"{error}; retrying from state"
    else:
        detail = f"{error}; retrying original request"
    _report_error(request, "runner.retry", detail, 0)
    time.sleep(max(1, request.retry_delay))


def _report_error(
    request: RunRequest,
    event_type: str,
    message: str,
    exit_code: int,
) -> None:
    if request.json_events:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "runner_version": __version__,
                    "type": event_type,
                    "timestamp": time.time(),
                    "message": message,
                    "exit_code": exit_code,
                },
            ),
            flush=True,
        )
        return

    prefix = "" if exit_code == 130 else "ERROR: "
    print(prefix + message, file=sys.stderr)


def _supervise(argv: Sequence[str]) -> int:
    if os.environ.get("AI_TASK_RUNNER_WORKER") == "1":
        return main(argv)

    request = RunRequest.from_namespace(parser().parse_args(argv))
    worker_args = list(argv)
    while True:
        env = dict(os.environ)
        env["AI_TASK_RUNNER_WORKER"] = "1"
        worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *worker_args], env=env)
        try:
            code = worker.wait()
        except KeyboardInterrupt:
            worker.terminate()
            return 130
        if code in (0, 1, 130):
            return code
        state = Path(request.project_root, request.work_dir, "state.json").resolve()
        if not state.is_file():
            return code
        _cleanup_orphan(request, worker.pid)
        _report_error(request, "runner.retry", f"worker exited unexpectedly ({code}); resuming saved state", 0)
        worker_args = [arg for arg in worker_args if arg not in {"--resume", "--force-new"}] + ["--resume"]
        time.sleep(max(1, request.retry_delay))


def _cleanup_orphan(request: RunRequest, worker_pid: int) -> None:
    path = Path(request.project_root, request.work_dir, ACTIVE_PROCESS_FILE).resolve()
    try:
        owner, child = map(int, path.read_text(encoding="ascii").split())
        if owner != worker_pid:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(child), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            os.killpg(child, signal.SIGKILL)
        path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


if __name__ == "__main__":
    raise SystemExit(_supervise(sys.argv[1:]))
