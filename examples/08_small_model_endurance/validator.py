#!/usr/bin/env python3
"""Deterministic validator for the small-model endurance case."""
from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import py_compile
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

REQUIRED_FILES = (
    "worklog.py",
    "taskflow/__init__.py",
    "taskflow/model.py",
    "taskflow/storage.py",
    "taskflow/service.py",
    "taskflow/cli.py",
    "README.md",
)
STATUSES = ("pending", "running", "completed", "failed", "cancelled")
PRIORITIES = ("low", "normal", "high", "critical")
MAX_SOURCE_LINES = 400
MIN_TESTS = 10


@dataclass
class Finding:
    code: str
    title: str
    details: list[str]
    fix: str
    report: Path


class Report:
    def __init__(self, root: Path) -> None:
        base = os.environ.get("AI_TASK_RUNNER_REPORT_DIR")
        report_root = Path(base) if base else root / ".ai-task-runner" / "validator-reports"
        self.root = root
        self.directory = report_root / "small-model-endurance"
        self.errors: list[Finding] = []

    def error(self, code: str, title: str, error: BaseException | str) -> None:
        text = str(error)
        path = self.write(f"{code.lower()}-{slug(title)}.txt", [
            f"Check: {title}",
            "Problem:",
            text,
            "",
            "Fix:",
            "Implement the specified behavior generically and keep the validator unchanged.",
        ])
        self.errors.append(
            Finding(
                code=code,
                title=title,
                details=excerpt(text),
                fix="Implement the specified behavior generically and rerun the validator.",
                report=path,
            )
        )

    def write(self, name: str, lines: Iterable[object]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / name
        path.write_text("\n".join(map(str, lines)).rstrip() + "\n", encoding="utf-8")
        return path

    def finish(self) -> int:
        status = "VALIDATION_FAILED" if self.errors else "VALIDATION_PASSED"
        self.write("summary.txt", [
            status,
            f"errors: {len(self.errors)}",
            f"report_dir: {relative(self.root, self.directory)}",
        ])
        error_lines: list[str] = []
        for finding in self.errors:
            error_lines.extend([
                f"[{finding.code}] {finding.title}",
                *[f"- {line}" for line in finding.details],
                f"Fix: {finding.fix}",
                f"Full report: {relative(self.root, finding.report)}",
                "",
            ])
        self.write("errors.txt", error_lines or ["No errors."])
        print(status)
        print(f"errors: {len(self.errors)}")
        print(f"report_dir: {relative(self.root, self.directory)}")
        for finding in self.errors[:10]:
            print(f"[{finding.code}] {finding.title}")
            for line in finding.details:
                print(f"- {line}")
            print(f"Fix: {finding.fix}")
            print(f"Full report: {relative(self.root, finding.report)}")
        return 1 if self.errors else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--state-file")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    report = Report(root)

    checks: list[tuple[str, str, Callable[[], None]]] = [
        ("R001", "Required files and line limits", lambda: check_files(root)),
        ("R002", "Standard-library implementation and compilation", lambda: check_source(root)),
        ("R003", "Project unit tests", lambda: check_tests(root)),
        ("R004", "CLI lifecycle and dependency behavior", lambda: check_lifecycle(root)),
        ("R005", "Filtering, ordering, update, and cancellation", lambda: check_queries(root)),
        ("R006", "Retry limit and stable error contract", lambda: check_retry_and_errors(root)),
        ("R007", "Import, export, and statistics", lambda: check_import_export_stats(root)),
        ("R008", "Event history and storage recovery", lambda: check_events_and_recovery(root)),
        ("R009", "Documentation contract", lambda: check_readme(root)),
    ]
    for code, title, check in checks:
        try:
            check()
        except Exception as error:  # each check reports independently
            report.error(code, title, error)
    return report.finish()


def check_files(root: Path) -> None:
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    require(not missing, f"missing files: {missing}")
    for name in REQUIRED_FILES[:-1]:
        path = root / name
        lines = path.read_text(encoding="utf-8").splitlines()
        require(len(lines) <= MAX_SOURCE_LINES, f"{name} has {len(lines)} lines; max {MAX_SOURCE_LINES}")


def check_source(root: Path) -> None:
    sources = [root / "worklog.py", *sorted((root / "taskflow").glob("*.py"))]
    allowed_local = {"taskflow"}
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
    forbidden: list[str] = []
    for path in sources:
        py_compile.compile(str(path), doraise=True)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            name = ""
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", 1)[0]
                    if root_name not in stdlib and root_name not in allowed_local:
                        forbidden.append(f"{relative(root, path)} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                root_name = node.module.split(".", 1)[0]
                if root_name not in stdlib and root_name not in allowed_local:
                    forbidden.append(f"{relative(root, path)} imports {node.module}")
    require(not forbidden, "non-standard-library imports:\n" + "\n".join(forbidden))


def check_tests(root: Path) -> None:
    test_dir = root / "tests"
    require(test_dir.is_dir(), "tests/ directory is missing")
    count = 0
    for path in test_dir.rglob("test*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count += sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test") for node in ast.walk(tree))
    require(count >= MIN_TESTS, f"found {count} test methods/functions; require at least {MIN_TESTS}")
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
    )
    require(result.returncode == 0, "project tests failed:\n" + result.stdout[-12000:])


def check_lifecycle(root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="worklog-life-") as temporary:
        workspace = Path(temporary)
        run_ok(root, workspace, "init")
        first = run_ok(root, workspace, "add", "--title", "Foundation", "--priority", "critical", "--tag", " core ", "--tag", "core", "--max-retries", "1")
        require_task(first, "T0001", "pending", "critical")
        require(first["tags"] == ["core"], f"tags were not normalized: {first['tags']!r}")

        second = run_ok(root, workspace, "add", "--title", "Dependent", "--priority", "high", "--tag", "api", "--tag", "urgent", "--depends-on", "T0001")
        require_task(second, "T0002", "pending", "high")
        require(second["depends_on"] == ["T0001"], f"unexpected dependencies: {second['depends_on']!r}")

        before = state_bytes(workspace)
        blocked = run_cli(root, workspace, "claim", "T0002", expected=2)
        require(error_code(blocked) == "DEPENDENCY_BLOCKED", f"wrong blocked error: {blocked}")
        require(state_bytes(workspace) == before, "blocked claim changed state")

        claimed = run_ok(root, workspace, "claim", "T0001")
        require_task(claimed, "T0001", "running", "critical")
        require(claimed["attempts"] == 1, f"claim did not increment attempts: {claimed}")
        completed = run_ok(root, workspace, "complete", "T0001")
        require_task(completed, "T0001", "completed", "critical")

        claimed_second = run_ok(root, workspace, "claim", "T0002")
        require_task(claimed_second, "T0002", "running", "high")
        run_ok(root, workspace, "complete", "T0002")

        shown = run_ok(root, workspace, "show", "T0001")
        require_task(shown, "T0001", "completed", "critical")
        listed = run_ok(root, workspace, "list")
        require(isinstance(listed, list) and [task["id"] for task in listed] == ["T0001", "T0002"], f"unexpected list order: {listed}")


def check_queries(root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="worklog-query-") as temporary:
        workspace = Path(temporary)
        run_ok(root, workspace, "init")
        low = run_ok(root, workspace, "add", "--title", "Low", "--priority", "low", "--tag", "old")
        normal = run_ok(root, workspace, "add", "--title", "Normal", "--tag", "api")
        high = run_ok(root, workspace, "add", "--title", "High", "--priority", "high", "--tag", "api")
        critical = run_ok(root, workspace, "add", "--title", "Critical", "--priority", "critical")
        require([item["id"] for item in run_ok(root, workspace, "list")] == [critical["id"], high["id"], normal["id"], low["id"]], "priority ordering is incorrect")
        require([item["id"] for item in run_ok(root, workspace, "list", "--tag", "api")] == [high["id"], normal["id"]], "tag filter is incorrect")
        require([item["id"] for item in run_ok(root, workspace, "list", "--priority", "low")] == [low["id"]], "priority filter is incorrect")

        updated = run_ok(root, workspace, "update", low["id"], "--title", "Updated", "--priority", "high", "--add-tag", "new", "--remove-tag", "old")
        require(updated["title"] == "Updated" and updated["priority"] == "high", f"update failed: {updated}")
        require(updated["tags"] == ["new"], f"update tag normalization failed: {updated}")
        require(updated["attempts"] == 0 and updated["status"] == "pending", "metadata update changed lifecycle fields")

        cancelled = run_ok(root, workspace, "cancel", normal["id"])
        require(cancelled["status"] == "cancelled", f"cancel failed: {cancelled}")
        require([item["id"] for item in run_ok(root, workspace, "list", "--status", "cancelled")] == [normal["id"]], "status filter is incorrect")


def check_retry_and_errors(root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="worklog-retry-") as temporary:
        workspace = Path(temporary)
        run_ok(root, workspace, "init")
        task = run_ok(root, workspace, "add", "--title", "Retry", "--max-retries", "1")
        invalid = run_cli(root, workspace, "complete", task["id"], expected=2)
        require(error_code(invalid) == "INVALID_TRANSITION", f"wrong transition error: {invalid}")
        run_ok(root, workspace, "claim", task["id"])
        failed = run_ok(root, workspace, "fail", task["id"], "--reason", "first failure")
        require(failed["status"] == "failed" and failed["last_error"] == "first failure", f"fail did not record reason: {failed}")
        run_ok(root, workspace, "retry", task["id"])
        second_claim = run_ok(root, workspace, "claim", task["id"])
        require(second_claim["attempts"] == 2, f"second claim attempts incorrect: {second_claim}")
        run_ok(root, workspace, "fail", task["id"], "--reason", "second failure")
        before = state_bytes(workspace)
        exhausted = run_cli(root, workspace, "retry", task["id"], expected=2)
        require(error_code(exhausted) == "RETRY_EXHAUSTED", f"wrong retry error: {exhausted}")
        require(state_bytes(workspace) == before, "exhausted retry changed state")

        missing = run_cli(root, workspace, "show", "T9999", expected=2)
        require(error_code(missing) == "TASK_NOT_FOUND", f"wrong missing-task error: {missing}")
        require_error_shape(missing)


def check_import_export_stats(root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="worklog-io-") as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        run_ok(root, workspace, "init")
        run_ok(root, workspace, "add", "--title", "Critical", "--priority", "critical", "--tag", "a", "--tag", "b")
        second = run_ok(root, workspace, "add", "--title", "Normal")
        run_ok(root, workspace, "claim", second["id"])
        run_ok(root, workspace, "complete", second["id"])

        stats = run_ok(root, workspace, "stats")
        require(stats["total"] == 2, f"wrong total: {stats}")
        require(all(key in stats["status"] for key in STATUSES), f"missing status counts: {stats}")
        require(all(key in stats["priority"] for key in PRIORITIES), f"missing priority counts: {stats}")
        require(stats["status"]["pending"] == 1 and stats["status"]["completed"] == 1, f"wrong status counts: {stats}")
        require(stats["priority"]["critical"] == 1 and stats["priority"]["normal"] == 1, f"wrong priority counts: {stats}")
        require(stats["ready"] == 1, f"wrong ready count: {stats}")

        json_path = Path(temporary) / "export.json"
        csv_path = Path(temporary) / "export.csv"
        run_ok(root, workspace, "export", "--format", "json", "--output", str(json_path))
        run_ok(root, workspace, "export", "--format", "csv", "--output", str(csv_path))
        exported = json.loads(json_path.read_text(encoding="utf-8"))
        require(isinstance(exported, list) and len(exported) == 2, "JSON export is invalid")
        with csv_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        require(len(rows) == 2, "CSV export row count is invalid")
        required_columns = {"id", "title", "status", "priority", "tags", "depends_on", "attempts", "max_retries", "created_at", "updated_at", "last_error"}
        require(required_columns <= set(rows[0]), f"CSV columns missing: {sorted(required_columns - set(rows[0]))}")
        require(";" in rows[0]["tags"], f"CSV tags are not semicolon-joined: {rows[0]['tags']!r}")

        import_path = Path(temporary) / "import.json"
        import_path.write_text(json.dumps([
            {"title": "Imported A", "priority": "high", "tags": ["x", "x", " y "]},
            {"title": "Imported B", "max_retries": 2},
        ]), encoding="utf-8")
        imported = run_ok(root, workspace, "import", "--input", str(import_path))
        require(isinstance(imported, list) and [item["id"] for item in imported] == ["T0003", "T0004"], f"import IDs are incorrect: {imported}")
        require(imported[0]["tags"] == ["x", "y"] and imported[0]["depends_on"] == [], f"import normalization failed: {imported}")

        invalid_path = Path(temporary) / "invalid.json"
        invalid_path.write_text(json.dumps([{"title": "Valid"}, {"priority": "low"}]), encoding="utf-8")
        before = run_ok(root, workspace, "list")
        result = run_cli(root, workspace, "import", "--input", str(invalid_path), expected=2)
        require_error_shape(result)
        after = run_ok(root, workspace, "list")
        require(after == before, "invalid import was not atomic")


def check_events_and_recovery(root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="worklog-recover-") as temporary:
        workspace = Path(temporary)
        run_ok(root, workspace, "init")
        task = run_ok(root, workspace, "add", "--title", "Recoverable")
        run_ok(root, workspace, "update", task["id"], "--add-tag", "safe")
        run_ok(root, workspace, "claim", task["id"])
        expected = run_ok(root, workspace, "list")

        hidden = workspace / ".worklog"
        event_path = hidden / "events.jsonl"
        lines = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        require(len(lines) >= 3, f"too few events: {lines}")
        require([item["seq"] for item in lines] == list(range(1, len(lines) + 1)), f"event sequence is not contiguous: {lines}")
        for event in lines:
            require(isinstance(event.get("timestamp"), str) and event["timestamp"], f"event timestamp missing: {event}")
            require(isinstance(event.get("action"), str) and event["action"], f"event action missing: {event}")
            require(isinstance(event.get("details"), dict), f"event details must be an object: {event}")

        state_path = hidden / "state.json"
        backup_path = hidden / "state.json.bak"
        require(backup_path.is_file(), "state backup is missing")
        require(json.loads(backup_path.read_text(encoding="utf-8")), "state backup is invalid JSON")
        state_path.write_text("{broken", encoding="utf-8")
        recovered = run_ok(root, workspace, "list")
        require(recovered == expected, f"backup recovery lost latest state:\nexpected={expected}\nactual={recovered}")
        require(json.loads(state_path.read_text(encoding="utf-8")), "main state was not restored after recovery")

        state_path.write_text("broken", encoding="utf-8")
        backup_path.write_text("broken", encoding="utf-8")
        corrupt = run_cli(root, workspace, "list", expected=3)
        require(error_code(corrupt) == "STORAGE_CORRUPT", f"wrong corruption error: {corrupt}")
        require_error_shape(corrupt)


def check_readme(root: Path) -> None:
    text = (root / "README.md").read_text(encoding="utf-8").lower()
    required = (
        "python 3.10",
        "taskflow/model.py",
        "taskflow/storage.py",
        "taskflow/service.py",
        "taskflow/cli.py",
        "state.json",
        "events.jsonl",
        "claim",
        "complete",
        "fail",
        "retry",
        "recovery",
        "python -m unittest discover -s tests -v",
    )
    missing = [item for item in required if item not in text]
    require(not missing, f"README is missing required topics/examples: {missing}")


def run_ok(root: Path, workspace: Path, *args: str) -> Any:
    result = run_cli(root, workspace, *args, expected=0)
    return result["payload"]


def run_cli(root: Path, workspace: Path, *args: str, expected: int) -> dict[str, Any]:
    command = [sys.executable, str(root / "worklog.py"), "--root", str(workspace), *args]
    completed = subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    require(
        completed.returncode == expected,
        "command returned unexpected code:\n"
        f"command={command}\nexpected={expected}\nactual={completed.returncode}\n"
        f"stdout={completed.stdout}\nstderr={completed.stderr}",
    )
    stream = completed.stdout if expected == 0 else completed.stderr
    require(stream.strip(), f"command produced no JSON on {'stdout' if expected == 0 else 'stderr'}: {command}")
    try:
        payload = json.loads(stream)
    except json.JSONDecodeError as error:
        raise AssertionError(f"command output is not exactly one JSON value:\n{stream}") from error
    other = completed.stderr if expected == 0 else completed.stdout
    require(not other.strip(), f"command wrote unexpected extra output: {other}")
    return {"payload": payload, "stdout": completed.stdout, "stderr": completed.stderr, "code": completed.returncode}


def require_task(task: Any, task_id: str, status: str, priority: str) -> None:
    require(isinstance(task, dict), f"task is not an object: {task!r}")
    required = {"id", "title", "status", "priority", "tags", "depends_on", "attempts", "max_retries", "created_at", "updated_at", "last_error"}
    require(required <= set(task), f"task fields missing: {sorted(required - set(task))}")
    require(task["id"] == task_id, f"expected {task_id}, got {task.get('id')}")
    require(task["status"] == status, f"expected {status}, got {task.get('status')}")
    require(task["priority"] == priority, f"expected {priority}, got {task.get('priority')}")


def require_error_shape(result: dict[str, Any]) -> None:
    payload = result["payload"]
    require(isinstance(payload, dict) and payload.get("ok") is False, f"error object missing ok=false: {payload}")
    error = payload.get("error")
    require(isinstance(error, dict), f"error field is invalid: {payload}")
    require(isinstance(error.get("code"), str) and error["code"], f"error code missing: {payload}")
    require(isinstance(error.get("message"), str) and error["message"], f"error message missing: {payload}")


def error_code(result: dict[str, Any]) -> str:
    require_error_shape(result)
    return str(result["payload"]["error"]["code"])


def state_bytes(workspace: Path) -> bytes:
    return (workspace / ".worklog" / "state.json").read_bytes()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def excerpt(text: str, limit: int = 10) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[:limit] + ([f"... {len(lines) - limit} more lines in Full report"] if len(lines) > limit else [])


def slug(text: str) -> str:
    return "-".join("".join(character.lower() if character.isalnum() else " " for character in text).split())[:80]


def relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
