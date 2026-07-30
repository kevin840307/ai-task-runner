#!/usr/bin/env python3
"""Template for validators that wrap an external exe, bat, jar, or CLI.

The external tool can write logs anywhere. This wrapper copies matching logs
into AI_TASK_RUNNER_REPORT_DIR/external-command/ and prints compact
paths for the agent.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from ai_task_runner_validator import ValidatorReport
except ImportError:  # Allows copying validator_interface.py next to this file.
    from validator_interface import ValidatorReport


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        help=(
            "External validator command. Repeat to pass multiple argv parts, "
            "for example: --command java --command -jar --command check.jar"
        ),
    )
    parser.add_argument(
        "--log-dir",
        action="append",
        default=[],
        help="Folder written by the external validator. Can be repeated.",
    )
    parser.add_argument(
        "--log-glob",
        default="**/*",
        help="Glob used under each --log-dir when copying logs.",
    )
    parser.add_argument("--timeout", type=int, default=300)
    return parser.parse_args()


def run_external(
    project_root: Path,
    command: list[str],
    timeout: int,
    result: ValidatorReport,
) -> int | None:
    if not command:
        result.error(
            "E000",
            "No external validator command configured",
            fix="Pass --validator-arg --command ... for each command argument.",
        )
        return None

    try:
        completed = subprocess.run(
            command,
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
            f"External validator timed out after {timeout} seconds",
            fix="Fix the generated project or increase the validator timeout.",
            report_name="external-command-output.txt",
            report_content=output,
        )
        return None

    output = completed.stdout or "No command output."
    result.write_report("external-command-output.txt", output)
    if completed.returncode != 0:
        result.error(
            "E101",
            f"External validator exited with code {completed.returncode}",
            details=[
                "Read external-command-output.txt first.",
                "Then inspect copied external logs listed in logs-index.txt.",
            ],
            fix="Use the external validator output and logs to repair the project.",
            report_name="external-command-output.txt",
            report_content=output,
        )
    return completed.returncode


def copy_logs(
    project_root: Path,
    log_dirs: list[str],
    log_glob: str,
    result: ValidatorReport,
) -> None:
    copied: list[str] = []
    missing: list[str] = []
    destination = result.report_dir / "external-logs"
    for raw_dir in log_dirs:
        source_dir = Path(raw_dir)
        if not source_dir.is_absolute():
            source_dir = project_root / source_dir
        if not source_dir.is_dir():
            missing.append(str(source_dir))
            continue
        for source in sorted(source_dir.glob(log_glob)):
            if not source.is_file():
                continue
            relative = safe_relative(source, source_dir)
            target = destination / source_dir.name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(result.display_path(target))

    index_lines = ["Copied external validator logs:"]
    index_lines.extend(copied or ["No matching log files copied."])
    if missing:
        index_lines.append("")
        index_lines.append("Missing log folders:")
        index_lines.extend(missing)
    result.write_report("logs-index.txt", index_lines)

    if missing:
        result.warning(
            "W201",
            "Some configured external log folders were not found",
            missing,
            fix="Check whether --log-dir points to the folder used by the external validator.",
        )
    if copied:
        result.warning(
            "W202",
            f"Copied {len(copied)} external log file(s)",
            [
                "Report index: "
                + result.display_path(result.report_dir / "logs-index.txt")
            ],
        )


def safe_relative(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return Path(path.name)


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    result = ValidatorReport(project_root, "external-command")

    run_external(project_root, args.command, args.timeout, result)
    copy_logs(project_root, args.log_dir, args.log_glob, result)
    return result.finish()


if __name__ == "__main__":
    sys.exit(main())
