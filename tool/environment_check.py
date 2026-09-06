#!/usr/bin/env python3
"""Fast local environment checks for AI Task Runner.

The tool is intentionally side-effect free. It checks only local executables,
Python packages, repository files, and writable UI/runtime directories.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

MIN_PYTHON = (3, 10)


def _row(name: str, status: str, detail: str, *, required: bool = True) -> dict:
    return {"name": name, "status": status, "detail": detail, "required": required}


def _writable(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(prefix="env-check-", dir=path, delete=False)
        temp = Path(handle.name)
        handle.close()
        temp.unlink(missing_ok=True)
        return True, str(path)
    except OSError as exc:
        return False, f"{path}: {exc}"


def check(repo_root: Path) -> dict:
    repo_root = repo_root.resolve()
    checks: list[dict] = []

    py_ok = sys.version_info >= MIN_PYTHON
    checks.append(_row(
        "Python",
        "pass" if py_ok else "fail",
        f"{sys.version.split()[0]} · {sys.executable}",
    ))

    for module, label in (("yaml", "PyYAML"), ("jinja2", "Jinja2")):
        found = importlib.util.find_spec(module) is not None
        checks.append(_row(label, "pass" if found else "fail", "Installed" if found else "Missing"))

    for relative, label in (
        ("ai_task_runner.py", "Runner entrypoint"),
        ("tool/workflow_dryrun.py", "Workflow dry-run"),
        ("runner/workflow/system/ai.yaml", "Default workflow"),
    ):
        path = repo_root / relative
        checks.append(_row(label, "pass" if path.is_file() else "fail", str(path)))

    ui_data_ok, ui_data_detail = _writable(repo_root / "ui" / "data")
    checks.append(_row("UI data directory", "pass" if ui_data_ok else "fail", ui_data_detail))

    backend_rows = []
    for name in ("qwen", "opencode"):
        candidates = [name, f"{name}.cmd"] if os.name == "nt" else [name]
        resolved = next((shutil.which(candidate) for candidate in candidates if shutil.which(candidate)), None)
        status = "pass" if resolved else "warn"
        detail = resolved or "Not found on PATH"
        backend_rows.append((name, resolved))
        checks.append(_row(f"Backend · {name}", status, detail, required=False))

    if not any(path for _, path in backend_rows):
        checks.append(_row("Usable backend", "warn", "Neither qwen nor opencode was found on PATH", required=False))

    failed = [item for item in checks if item["required"] and item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warn"]
    return {
        "ok": not failed,
        "status": "fail" if failed else ("warn" if warnings else "pass"),
        "repo_root": str(repo_root),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local AI Task Runner environment")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check(Path(args.repo_root))
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"Environment: {result['status'].upper()}")
        for item in result["checks"]:
            print(f"[{item['status'].upper():4}] {item['name']}: {item['detail']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
