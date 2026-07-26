#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


EXPECTED_REPORT = {
    "total_revenue": 333.19,
    "order_count": 6,
    "units_by_product": {"Doodad": 5, "Gadget": 6, "Widget": 6},
    "revenue_by_region": {
        "East": 76.23,
        "North": 79.96,
        "South": 59.0,
        "West": 118.0,
    },
    "top_product_by_revenue": {
        "product": "Gadget",
        "revenue": 177.0,
    },
    "date_range": {
        "start": "2026-07-01",
        "end": "2026-07-03",
    },
}


def fail(message: str) -> int:
    print(message)
    return 1


def require_completed_tasks(state_path: Path, minimum: int) -> int | None:
    if not state_path.is_file():
        return fail("missing runner state")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    tasks = state.get("tasks", [])
    if len(tasks) < minimum:
        return fail(f"expected at least {minimum} planned tasks, got {len(tasks)}")
    if any(task.get("status") != "completed" for task in tasks):
        return fail("not all planned tasks are completed")
    if any(not task.get("last_review", {}).get("completed") for task in tasks):
        return fail("every task must be reviewed as completed")
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()
    root = Path(args.project_root)

    state_error = require_completed_tasks(Path(args.state_file), 3)
    if state_error is not None:
        return state_error

    script = root / "analyze_sales.py"
    if not script.is_file():
        return fail("missing analyze_sales.py")

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--input",
            "input/sales.csv",
            "--json",
            "report.json",
            "--markdown",
            "report.md",
        ],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
    )
    if result.returncode != 0:
        return fail("analyze_sales.py failed:\n" + result.stdout)

    report_path = root / "report.json"
    if not report_path.is_file():
        return fail("missing report.json")
    actual = json.loads(report_path.read_text(encoding="utf-8"))
    if actual != EXPECTED_REPORT:
        return fail("unexpected report.json:\n" + json.dumps(actual, indent=2, sort_keys=True))

    markdown = (root / "report.md").read_text(encoding="utf-8") if (root / "report.md").is_file() else ""
    required_markdown = [
        "# Sales Report",
        "Total revenue",
        "333.19",
        "| Region | Revenue |",
        "Gadget",
    ]
    missing = [text for text in required_markdown if text not in markdown]
    if missing:
        return fail("report.md missing: " + ", ".join(missing))

    readme = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").is_file() else ""
    for heading in ("## Usage", "## Outputs", "## Assumptions"):
        if heading not in readme:
            return fail(f"README.md missing {heading}")

    print("PASS: csv analyzer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
