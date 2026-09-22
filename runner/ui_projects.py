"""Best-effort registration for projects visible in the local UI."""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_TIMEOUT_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.05
STALE_LOCK_SECONDS = 60.0


def register_ui_project(project_root: str | Path, *, repo_root: Path | None = None) -> None:
    """Add a project root to the UI sidebar project list.

    CLI runs are allowed to work without the UI being open. Registration is
    therefore best-effort: project execution must not fail because the UI state
    file is unavailable or temporarily malformed.
    """
    try:
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            return
        projects_file = (
            (repo_root or Path(__file__).resolve().parents[1])
            / "ui"
            / "data"
            / "projects.json"
        )
        projects_file.parent.mkdir(parents=True, exist_ok=True)
        with _project_file_lock(projects_file):
            try:
                rows = json.loads(projects_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                rows = []
            if not isinstance(rows, list):
                rows = []

            key = os.path.normcase(os.path.abspath(str(root)))
            existing_name = ""
            items = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_key = os.path.normcase(os.path.abspath(str(row.get("path") or "")))
                if row_key == key:
                    existing_name = str(row.get("name") or "")
                    continue
                items.append(row)
            items.insert(0, {"name": existing_name or root.name or str(root), "path": str(root)})

            tmp = projects_file.with_name(
                f"{projects_file.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            tmp.write_text(
                json.dumps(items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, projects_file)
    except OSError:
        return


@contextmanager
def _project_file_lock(projects_file: Path):
    lock = projects_file.with_suffix(projects_file.suffix + ".lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    handle: int | None = None
    while handle is None:
        try:
            handle = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            _remove_stale_lock(lock)
            if time.monotonic() >= deadline:
                raise OSError(f"timed out waiting for UI project lock: {lock}")
            time.sleep(LOCK_POLL_SECONDS)
    try:
        os.write(handle, f"{os.getpid()}\n".encode("ascii"))
        yield
    finally:
        os.close(handle)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _remove_stale_lock(lock: Path) -> None:
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return
    if age <= STALE_LOCK_SECONDS:
        return
    try:
        lock.unlink()
    except OSError:
        pass


__all__ = ["register_ui_project"]
