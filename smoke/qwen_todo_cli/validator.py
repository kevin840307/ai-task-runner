#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


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


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "todo_cli.py", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
    )


def command_failure(command: tuple[str, ...], result: subprocess.CompletedProcess[str]) -> str:
    output = result.stdout.strip() or "(no stdout/stderr)"
    hint = ""
    if not result.stdout.strip():
        hint = (
            "\nThe CLI must not fail silently. Make this exact command return 0 "
            "or print a clear error before exiting non-zero."
        )
    return (
        f"command failed {command} with exit code {result.returncode}:\n"
        f"{output}{hint}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()
    root = Path(args.project_root)

    state_error = require_completed_tasks(Path(args.state_file), 3)
    if state_error is not None:
        return state_error

    script = root / "todo_cli.py"
    if not script.is_file():
        return fail("missing todo_cli.py")

    db_path = root / "todos.json"
    if db_path.exists():
        db_path.unlink()

    commands = [
        ("--db", "todos.json", "add", "Write docs", "--priority", "high"),
        ("--db", "todos.json", "add", "Fix parser", "--priority", "medium"),
        ("--db", "todos.json", "add", "Ship release", "--priority", "low"),
        ("--db", "todos.json", "done", "2"),
        ("--db", "todos.json", "delete", "3"),
    ]
    for command in commands:
        result = run_cli(root, *command)
        if result.returncode != 0:
            return fail(command_failure(command, result))

    listed = run_cli(root, "--db", "todos.json", "list", "--format", "json")
    if listed.returncode != 0:
        return fail(command_failure(("--db", "todos.json", "list", "--format", "json"), listed))
    try:
        todos = json.loads(listed.stdout)
    except json.JSONDecodeError as error:
        return fail(f"list --format json did not print JSON: {error}\n{listed.stdout}")
    expected_todos = [
        {"id": 1, "text": "Write docs", "priority": "high", "done": False},
        {"id": 2, "text": "Fix parser", "priority": "medium", "done": True},
    ]
    if todos != expected_todos:
        return fail("unexpected list output:\n" + json.dumps(todos, indent=2, sort_keys=True))

    stored = json.loads(db_path.read_text(encoding="utf-8"))
    if stored != expected_todos:
        return fail("unexpected stored JSON:\n" + json.dumps(stored, indent=2, sort_keys=True))

    exported = run_cli(root, "--db", "todos.json", "export", "--output", "summary.md")
    if exported.returncode != 0:
        return fail(command_failure(("--db", "todos.json", "export", "--output", "summary.md"), exported))
    summary = (root / "summary.md").read_text(encoding="utf-8") if (root / "summary.md").is_file() else ""
    for text in ("# Todo Summary", "## Open", "Write docs", "## Completed", "Fix parser"):
        if text not in summary:
            return fail("summary.md missing: " + text)

    readme = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").is_file() else ""
    for heading in ("## Usage", "## Data format", "## Commands", "## Examples"):
        if heading not in readme:
            return fail(f"README.md missing {heading}")

    print("PASS: todo cli")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
