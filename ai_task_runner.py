#!/usr/bin/env python3
"""Thin CLI adapter for the shared AI Task Runner entry point."""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections.abc import Sequence
from pathlib import Path

from runner.defaults import (
    DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_BACKEND,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_CYCLES,
    DEFAULT_PLANNING_TIMEOUT,
    DEFAULT_FINAL_AI_VALIDATIONS,
    DEFAULT_FINAL_AI_REQUIRED_PASSES,
    DEFAULT_VALIDATOR_TIMEOUT,
)
from runner.api import RunRequest, run
from runner.version import __version__
from runner.backends import backend_names

# Compatibility exports for existing callers; new integrations should use runner.run.
from runner.errors import RunnerError
from runner.models import RunState, State, Task
from runner.prompting import (
    ai_validator_prompt,
    execution_prompt,
    plan_prompt,
    review_prompt,
)
from runner.support import parse_tasks


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
        help="extra instructions for AI validation",
    )
    command_parser.add_argument(
        "--backend",
        choices=backend_names(),
        default=DEFAULT_BACKEND,
    )
    command_parser.add_argument("--command")
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
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
    )
    command_parser.add_argument(
        "--max-cycles",
        type=int,
        default=DEFAULT_MAX_CYCLES,
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
        type=int,
        default=DEFAULT_FINAL_AI_VALIDATIONS,
        help="maximum independent Final AI validation runs; each uses a fresh session",
    )
    command_parser.add_argument(
        "--final-ai-required-passes",
        type=int,
        default=DEFAULT_FINAL_AI_REQUIRED_PASSES,
        help="Final AI PASS results required; any explicit FAIL still fails the cycle",
    )
    command_parser.add_argument(
        "--retry-max-wait",
        type=float,
        default=300,
        help="maximum model-call retry wait",
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
            return run(request).exit_code
        except KeyboardInterrupt:
            _report_error(request, "runner.stopped", "Stopped; use --resume", 130)
            return 130
        except Exception as error:
            log = Path(request.project_root, request.work_dir, "exception.log").resolve()
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as file:
                file.write(
                    f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"{type(error).__name__}: {error}\n{traceback.format_exc()}"
                )
            state_file = Path(
                request.project_root, request.work_dir, "state.json"
            ).resolve()
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


if __name__ == "__main__":
    raise SystemExit(main())
