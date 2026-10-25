"""Small shared filesystem/project primitives used by UI and Runner.

This module intentionally has no Runner/UI dependencies so both processes can
share path identity and registry locking without crossing architecture boundaries.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
import threading
from contextlib import contextmanager
from pathlib import Path

LOCK_TIMEOUT_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.05
_IN_PROCESS_LOCK = threading.RLock()


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


def _project_lock_path(projects_file: Path) -> Path:
    """Return a stable machine-local lock path without dirtying the repository."""
    identity = os.path.normcase(os.path.abspath(str(projects_file)))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    root = Path(tempfile.gettempdir()) / "ai-task-runner-project-locks"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{digest}.lock"


def _try_os_file_lock(handle: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(handle, 0, os.SEEK_SET)
        msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_os_file_lock(handle: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(handle, 0, os.SEEK_SET)
        msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def project_file_lock(projects_file: Path):
    """Thread-safe and kernel-backed cross-process project registry lock."""
    # Keep one stable sidecar outside the repository. A kernel lock is released
    # automatically when a process exits, so a crashed UI/Runner cannot leave a
    # stale sentinel that blocks later registrations. The in-process RLock also
    # keeps threads from needlessly contending through the OS lock.
    with _IN_PROCESS_LOCK:
        lock = _project_lock_path(projects_file)
        handle = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
        acquired = False
        try:
            # msvcrt.locking() operates on a byte range. Initializing one byte is
            # harmless if two first-time openers race; both still contend on byte 0.
            if os.fstat(handle).st_size == 0:
                os.write(handle, b"\0")
            deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            while not acquired:
                try:
                    _try_os_file_lock(handle)
                    acquired = True
                except OSError as error:
                    if time.monotonic() >= deadline:
                        raise OSError(
                            f"timed out waiting for UI project lock: {lock}"
                        ) from error
                    time.sleep(LOCK_POLL_SECONDS)
            yield
        finally:
            try:
                if acquired:
                    _release_os_file_lock(handle)
            finally:
                # Closing the handle is the final kernel-level release even if
                # an explicit unlock reports an OS error during teardown.
                os.close(handle)


__all__ = ["path_key", "project_file_lock", "project_path_key"]
