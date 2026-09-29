#!/usr/bin/env python3
"""Thin CLI adapter for AI Task Runner."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence

from runner.api import RunRequest, run, state_files
from runner.agent import backend_names
from runner.config.defaults import (
    DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_BACKEND,
    DEFAULT_FINAL_AI_REQUIRED_PASSES,
    DEFAULT_FINAL_AI_VALIDATIONS,
    DEFAULT_PLANNING_TIMEOUT,
    DEFAULT_STAGE_RETRIES,
    DEFAULT_VALIDATOR_TIMEOUT,
    DEFAULT_WATCHDOG_INTERVAL,
    DEFAULT_WORKER_HANG_TIMEOUT,
)
from runner.errors import ConfigurationError
from runner.plugins.registry import add_plugin_arguments, discover_plugins
from runner.runtime.supervisor import supervise_cli
from runner.version import __version__


def parser() -> argparse.ArgumentParser:
    discover_plugins()
    value = argparse.ArgumentParser(description="Reusable AI task runner")
    value.add_argument("--goal")
    value.add_argument("--goal-file")
    value.add_argument("--project-root", default=".")
    value.add_argument("--project-name", default="")
    value.add_argument("--script", help="YAML List batch file")
    value.add_argument("--workflow", help="Workflow YAML")
    value.add_argument("--validator", help="validator.py path or literal 'ai'")
    value.add_argument("--validator-prompt", default="")
    value.add_argument("--ai-validator-prompt", default="")
    value.add_argument("--ai-validator-prompt-file")
    value.add_argument("--backend", choices=backend_names(), default=DEFAULT_BACKEND)
    value.add_argument("--command")
    value.add_argument("--sandbox", action="store_true")
    value.add_argument("--agent-arg", action="append", default=[])
    value.add_argument("--validator-arg", action="append", default=[])
    value.add_argument("--protect-file", action="append", default=[])

    value.add_argument(
        "--validator-timeout", type=int, default=DEFAULT_VALIDATOR_TIMEOUT
    )
    value.add_argument("--agent-timeout", type=int, default=DEFAULT_AGENT_TIMEOUT)
    value.add_argument(
        "--planning-timeout", type=int, default=DEFAULT_PLANNING_TIMEOUT
    )
    value.add_argument(
        "--agent-idle-after-change-timeout",
        type=float,
        default=DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
    )
    value.add_argument(
        "--watchdog-interval", type=float, default=DEFAULT_WATCHDOG_INTERVAL
    )
    value.add_argument(
        "--worker-hang-timeout", type=float, default=DEFAULT_WORKER_HANG_TIMEOUT
    )
    value.add_argument(
        "--stage-retries",
        type=int,
        default=DEFAULT_STAGE_RETRIES,
        help="technical Stage retries; -1 keeps retrying with Fresh Session rotation",
    )
    value.add_argument("--retry-delay", type=float, default=5, help="seconds before retrying a technical failure")
    value.add_argument("--retry-max-delay", type=float, default=300, help="maximum seconds between transient service retries")

    value.add_argument(
        "--final-ai-validations",
        "--ai-validator-count",
        dest="final_ai_validations",
        type=int,
        default=DEFAULT_FINAL_AI_VALIDATIONS,
    )
    value.add_argument(
        "--final-ai-required-passes",
        type=int,
        default=DEFAULT_FINAL_AI_REQUIRED_PASSES,
    )
    value.add_argument("--ai-validator-yolo", action="store_true")
    value.add_argument(
        "--readonly-safety",
        choices=("restore", "observe"),
        default="restore",
    )

    add_plugin_arguments(value)

    value.add_argument("--work-dir", default=".ai-task-runner")
    value.add_argument(
        "--no-ui-project-register",
        dest="auto_register_ui_project",
        action="store_false",
    )
    value.add_argument("--json-events", action="store_true")
    value.add_argument("--resume", action="store_true")
    value.add_argument("--force-new", action="store_true")
    return value


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


def _report_error(
    request: RunRequest,
    event_type: str,
    message: str,
    exit_code: int,
) -> None:
    if request.json_events:
        print(json.dumps({
            "schema_version": 1,
            "runner_version": __version__,
            "type": event_type,
            "action": event_type.rsplit(".", 1)[-1],
            "timestamp": time.time(),
            "message": message,
            "exit_code": exit_code,
        }), flush=True)
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
