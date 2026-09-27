"""Small shared filesystem/project primitives used by UI and Runner.

This module intentionally has no Runner/UI dependencies so both processes can
share path identity and registry locking without crossing architecture boundaries.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_TIMEOUT_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.05
STALE_LOCK_SECONDS = 60.0


def path_key(path: str | Path) -> str:
    """Return one filesystem identity for equivalent path spellings when possible."""
    value = Path(path).expanduser()
    try:
        stat = value.absolute().stat()
        inode = int(getattr(stat, "st_ino", 0) or 0)
        device = int(getattr(stat, "st_dev", 0) or 0)
        if inode:
            return f"fs:{device}:{inode}"
    except OSError:
        pass
    return os.path.normcase(os.path.abspath(str(value)))


def project_path_key(path: str | Path) -> str:
    """Backward-compatible project registry name for the shared path identity."""
    return path_key(path)


@contextmanager
def project_file_lock(projects_file: Path):
    """Cross-process lock for read-modify-write project registry operations."""
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


__all__ = ["path_key", "project_file_lock", "project_path_key"]
