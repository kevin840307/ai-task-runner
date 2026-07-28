#!/usr/bin/env python3
"""Template for validators that run a command and inspect files.

Edit COMMAND and CHECKS for the target project.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    from ai_task_runner_validator import ValidatorReport
except ImportError:  # Allows copying validator_interface.py next to this file.
    from validator_interface import ValidatorReport

COMMAND: list[str] = []  # Example: [sys.executable, "main.py", "--input", "input/data.csv"]
REQUIRED_FILES: list[str] = []
FORBIDDEN_FILES: list[str] = []
TEXT_MUST_CONTAIN: dict[str, list[str]] = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    return parser.parse_args()


def run_command(project_root: Path, timeout: int, result: ValidatorReport) -> None:
    if not COMMAND:
        return
    try:
        completed = subprocess.run(
            COMMAND,
            cwd=project_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        result.error(
            "E100",
            f"Command timed out after {timeout} seconds",
            fix="Make the command finish within the validator timeout.",
            report_name="command-timeout.txt",
            report_content=output,
        )
        return

    output = completed.stdout or ""
    result.write_report("command-output.txt", output or "No command output.")
    if completed.returncode != 0:
        result.error(
            "E101",
            f"Command exited with code {completed.returncode}",
            fix="Fix the implementation so the command exits successfully.",
            report_name="command-output.txt",
            report_content=output,
        )


def check_files(project_root: Path, result: ValidatorReport) -> None:
    for relative in REQUIRED_FILES:
        if not (project_root / relative).exists():
            result.error("E201", f"Missing required file: {relative}", fix="Create the required file.")

    for relative in FORBIDDEN_FILES:
        if (project_root / relative).exists():
            result.error("E202", f"Forbidden file exists: {relative}", fix="Remove the forbidden generated file.")

    for relative, expected_fragments in TEXT_MUST_CONTAIN.items():
        path = project_root / relative
        if not path.exists():
            result.error("E301", f"Cannot inspect missing file: {relative}", fix="Create the file before validating its content.")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        missing = [fragment for fragment in expected_fragments if fragment not in text]
        if missing:
            result.error(
                "E302",
                f"{relative} is missing {len(missing)} required text fragment(s)",
                details=[f"missing: {fragment}" for fragment in missing],
                fix="Update the file content to satisfy the required contract.",
                report_name=f"{relative.replace('/', '__').replace(chr(92), '__')}.txt",
                report_content=text,
            )


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    _state_file = Path(args.state_file).resolve()
    result = ValidatorReport(project_root, "command-and-files")

    if not COMMAND and not REQUIRED_FILES and not FORBIDDEN_FILES and not TEXT_MUST_CONTAIN:
        result.warning("W000", "Template has no checks configured yet")

    run_command(project_root, args.timeout, result)
    check_files(project_root, result)
    return result.finish()


if __name__ == "__main__":
    sys.exit(main())
