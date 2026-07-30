#!/usr/bin/env python3
"""Copy-and-edit Python validator template.

Runner contract:
- exit code 0: pass
- exit code != 0: fail and retry
- stdout/stderr: feedback for the next agent attempt

Keep stdout short. Save full evidence through ValidatorReport; the runner supplies AI_TASK_RUNNER_REPORT_DIR.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from ai_task_runner_validator import ValidatorReport
except ImportError:  # Allows copying validator_interface.py next to this file.
    from validator_interface import ValidatorReport


def run_checks(project_root: Path, state_file: Path, result: ValidatorReport) -> None:
    """Replace this function with project-specific checks."""
    _ = state_file

    # Example warning so the copied template is obviously not a real validator yet.
    result.warning(
        "W000",
        "No project checks are configured yet",
        ["Edit run_checks() and add the checks that define success for this project."],
    )

    # Example hard failure:
    # required_file = project_root / "README.md"
    # if not required_file.exists():
    #     result.error(
    #         "E001",
    #         "Missing README.md",
    #         ["Expected README.md at the project root."],
    #         "Create README.md with the required project instructions.",
    #     )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    state_file = Path(args.state_file).resolve()

    result = ValidatorReport(project_root)
    run_checks(project_root, state_file, result)
    return result.finish()


if __name__ == "__main__":
    sys.exit(main())
