"""Project snapshot/change helpers shared by stages, recovery, and safety."""
from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from ..utils.files import copy_path, digest, remove_path

READONLY_EXCLUDE_DIRS = frozenset({
    ".git", ".ai-task-runner", ".idea", ".venv", ".vs", "__pycache__",
    "bin", "build", "coverage", "dist", "node_modules", "obj", "target",
})
STALE_TEMP_SECONDS = 7 * 24 * 60 * 60
STALE_TEMP_PREFIXES = ("ai-task-runner-readonly-*", "ai-task-runner-protect-*")


def excluded_dirs(root: Path, work: Path) -> set[str]:
    excluded = set(READONLY_EXCLUDE_DIRS)
    if work.is_relative_to(root):
        excluded.add(work.relative_to(root).parts[0])
    return excluded


def tree_manifest(root: Path, excluded: set[str]) -> dict[str, tuple[str, str | None]]:
    result: dict[str, tuple[str, str | None]] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = [name for name in directories if name not in excluded]
        for name in list(directories):
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative] = ("link", os.readlink(path))
                directories.remove(name)
            else:
                result[relative] = ("dir", "")
        for name in files:
            path = base / name
            relative = path.relative_to(root).as_posix()
            result[relative] = (
                "link" if path.is_symlink() else "file",
                os.readlink(path) if path.is_symlink() else digest(path),
            )
    return result


def project_manifest(root: Path, work: Path) -> dict[str, tuple[str, str | None]]:
    return tree_manifest(root, excluded_dirs(root, work))


def changed_project_files(root: Path, work: Path, before: dict[str, tuple[str, str | None]]) -> list[str]:
    after = project_manifest(root, work)
    changed: list[str] = []
    for path in set(before) | set(after):
        if before.get(path) == after.get(path):
            continue
        if before.get(path, (None, None))[0] == "dir" or after.get(path, (None, None))[0] == "dir":
            continue
        changed.append(path)
    return sorted(changed)


def restore_project_changes(root: Path, backup: Path, changed: Sequence[str]) -> None:
    paths = [Path(relative) for relative in changed]
    for relative in sorted(paths, key=lambda value: len(value.parts), reverse=True):
        remove_path(root / relative)
    for relative in sorted(paths, key=lambda value: len(value.parts)):
        source, target = backup / relative, root / relative
        if not (target.exists() or target.is_symlink()) and (source.exists() or source.is_symlink()):
            copy_path(source, target)


def cleanup_stale_artifacts(work: Path, temp_root: Path | None = None, older_than: float = STALE_TEMP_SECONDS) -> None:
    work.mkdir(parents=True, exist_ok=True)
    for path in work.glob("*.tmp"):
        remove_path(path)
    cutoff = time.time() - older_than
    root = temp_root or Path(tempfile.gettempdir())
    for pattern in STALE_TEMP_PREFIXES:
        for path in root.glob(pattern):
            try:
                if path.stat().st_mtime < cutoff:
                    remove_path(path)
            except OSError:
                continue


__all__ = [
    "READONLY_EXCLUDE_DIRS", "STALE_TEMP_PREFIXES", "STALE_TEMP_SECONDS", "changed_project_files",
    "cleanup_stale_artifacts", "excluded_dirs",
    "project_manifest", "restore_project_changes", "tree_manifest",
]
