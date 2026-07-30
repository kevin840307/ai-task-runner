#!/usr/bin/env python3
"""Audit Task decomposition for the small-model endurance case."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

REQUIREMENTS = tuple(f"R{index:02d}" for index in range(1, 19))
REQUIREMENT_RE = re.compile(r"\bR(?:0[1-9]|1[0-8])\b", re.IGNORECASE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=".ai-task-runner/state.json")
    args = parser.parse_args()
    path = Path(args.state)
    if not path.is_file():
        print(json.dumps({"ok": False, "error": f"state not found: {path}"}, indent=2))
        return 2

    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data.get("tasks", [])
    titles = [str(task.get("title", "")).strip() for task in tasks]
    duplicates = sorted(title for title, count in Counter(titles).items() if title and count > 1)

    coverage: dict[str, list[str]] = {requirement: [] for requirement in REQUIREMENTS}
    broad: list[dict[str, object]] = []
    missing_ids: list[str] = []
    task_rows: list[dict[str, object]] = []

    for task in tasks:
        task_id = str(task.get("id", ""))
        title = str(task.get("title", ""))
        criteria = task.get("acceptance_criteria", [])
        text = "\n".join([title, str(task.get("description", "")), *map(str, criteria)])
        ids = sorted({item.upper() for item in REQUIREMENT_RE.findall(text)})
        for requirement in ids:
            coverage[requirement].append(task_id)
        if not ids:
            missing_ids.append(task_id or title)
        if len(ids) >= 6:
            broad.append({"id": task_id, "title": title, "requirements": ids})
        task_rows.append(
            {
                "id": task_id,
                "title": title,
                "status": task.get("status"),
                "attempts": task.get("attempts", 0),
                "requirements": ids,
            }
        )

    uncovered = [requirement for requirement, owners in coverage.items() if not owners]
    total_attempts = sum(int(task.get("attempts", 0) or 0) for task in tasks)
    retries = sum(max(0, int(task.get("attempts", 0) or 0) - 1) for task in tasks)
    report = {
        "ok": not uncovered and not duplicates,
        "run": {
            "completed": bool(data.get("completed")),
            "stage": data.get("stage"),
            "cycle": data.get("cycle"),
            "task_count": len(tasks),
            "completed_tasks": sum(task.get("status") == "completed" for task in tasks),
            "total_attempts": total_attempts,
            "retry_attempts": retries,
            "validator_failure_count": data.get("validator_failure_count", 0),
        },
        "plan": {
            "covered_requirements": len(REQUIREMENTS) - len(uncovered),
            "total_requirements": len(REQUIREMENTS),
            "uncovered_requirements": uncovered,
            "duplicate_titles": duplicates,
            "tasks_without_requirement_ids": missing_ids,
            "broad_task_warnings": broad,
        },
        "tasks": task_rows,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
