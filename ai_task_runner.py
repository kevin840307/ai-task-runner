#!/usr/bin/env python3
"""Thin CLI adapter for the shared AI Task Runner entry point."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence

from runner.api import RunRequest, run, state_files
from runner.backends.registry import backend_names
from runner.config.defaults import (
    DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_API_WAIT_TIMEOUT,
    DEFAULT_BACKEND,
    DEFAULT_FINAL_AI_REQUIRED_PASSES,
    DEFAULT_FINAL_AI_VALIDATIONS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_CYCLES,
    DEFAULT_PLANNING_TIMEOUT,
    DEFAULT_REVIEW_RETRIES,
    DEFAULT_VALIDATOR_TIMEOUT,
    DEFAULT_WATCHDOG_INTERVAL,
)
from runner.errors import ConfigurationError
from runner.extensions import discover_extensions
from runner.plugins.registry import add_plugin_arguments
from runner.runtime.supervisor import supervise_cli
from runner.version import __version__


def parser() -> argparse.ArgumentParser:
    discover_extensions()
    command_parser = argparse.ArgumentParser(description="Reusable AI task runner")
    command_parser.add_argument("--goal")
    command_parser.add_argument(
        "--goal-file",
        help="UTF-8 text file containing the goal; mutually exclusive with --goal",
    )
    command_parser.add_argument("--project-root", default=".")
    command_parser.add_argument("--script", help="YAML array of prompt + validator items")
    command_parser.add_argument(
        "--workflow",
        help="linear Workflow YAML; omitted selects file/ai/mixed from validator options",
    )
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
    command_parser.add_argument("--validator-timeout", type=int, default=DEFAULT_VALIDATOR_TIMEOUT)
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
        help="same-session retries before fresh recovery; -1 retries until PASS, 0 disables same-session retry",
    )
    command_parser.add_argument(
        "--review-retries",
        type=int,
        default=DEFAULT_REVIEW_RETRIES,
        help="AI Review retries before skip; -1 retries until PASS, 0 disables retry",
    )
    command_parser.add_argument(
        "--max-cycles",
        type=int,
        default=DEFAULT_MAX_CYCLES,
        help="maximum workflow/replan cycles; -1 means unlimited (default), 0 disables replan",
    )
    command_parser.add_argument("--retry-delay", type=float, default=2, help="logical task retry delay")
    command_parser.add_argument("--retry-wait", type=float, default=5, help="initial model-call retry wait")
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
    command_parser.add_argument("--retry-max-wait", type=float, default=300, help="maximum model-call retry wait")
    add_plugin_arguments(command_parser)
    command_parser.add_argument("--work-dir", default=".ai-task-runner")
    command_parser.add_argument("--json-events", action="store_true", help="emit JSON Lines progress events")
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
    try:
        return run(request).exit_code
    except KeyboardInterrupt:
        _report_error(request, "runner.stopped", "Stopped; use --resume", 130)
        return 130
    except (ConfigurationError, ValueError) as error:
        _report_error(request, "runner.failed", str(error), 1)
        return 1


def _report_error(request: RunRequest, event_type: str, message: str, exit_code: int) -> None:
    if request.json_events:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "runner_version": __version__,
                    "type": event_type,
                    "action": event_type.rsplit(".", 1)[-1],
                    "timestamp": time.time(),
                    "message": message,
                    "exit_code": exit_code,
                }
            ),
            flush=True,
        )
        return
    prefix = "" if exit_code == 130 else "ERROR: "
    print(prefix + message, file=sys.stderr)


def _request(argv: Sequence[str]) -> RunRequest:
    return RunRequest.from_namespace(parser().parse_args(argv))


def _supervise(argv: Sequence[str]) -> int:
    return supervise_cli(
        argv,
        worker_script=__file__,
        request_factory=_request,
        worker_entry=main,
        state_locator=state_files,
    )


if __name__ == "__main__":
    raise SystemExit(_supervise(sys.argv[1:]))
