#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def fail(message: str) -> int:
    print(message)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()
    root = Path(args.project_root)
    state_path = Path(args.state_file)
    data = json.loads((root / "input" / "release.json").read_text(encoding="utf-8"))

    if not state_path.is_file():
        return fail("missing runner state")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    tasks = state.get("tasks", [])
    if len(tasks) < 3:
        return fail(f"expected at least 3 planned tasks, got {len(tasks)}")
    if any(task.get("status") != "completed" for task in tasks):
        return fail("not all planned tasks are completed")
    if any(not task.get("last_review", {}).get("completed") for task in tasks):
        return fail("every task must be reviewed as completed")

    version = root / "VERSION"
    if not version.is_file() or version.read_text(encoding="utf-8").strip() != data["version"]:
        return fail("VERSION mismatch")

    changelog = root / "CHANGELOG.md"
    if not changelog.is_file():
        return fail("missing CHANGELOG.md")
    expected_changelog = [
        "# Changelog",
        f"## {data['version']} - {data['date']}",
        "### Added",
        *[f"- {item}" for item in data["added"]],
        "### Fixed",
        *[f"- {item}" for item in data["fixed"]],
    ]
    actual_changelog = [
        line for line in changelog.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if actual_changelog != expected_changelog:
        return fail("unexpected CHANGELOG.md:\n" + "\n".join(actual_changelog))

    summary_path = root / "release_summary.json"
    if not summary_path.is_file():
        return fail("missing release_summary.json")
    expected_summary = {
        "name": data["name"],
        "version": data["version"],
        "added_count": len(data["added"]),
        "fixed_count": len(data["fixed"]),
        "release_date": data["date"],
    }
    if json.loads(summary_path.read_text(encoding="utf-8")) != expected_summary:
        return fail("release_summary.json mismatch")

    print("PASS: single prompt todo split")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
