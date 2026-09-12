"""Project snapshot/change helpers shared by stages, recovery, and safety."""
from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from ..utils.files import copy_path, digest, io_path, remove_path

# Runtime/tool/build artifacts are not project source and must never create
# readonly/protected-file failures. Match directory names case-insensitively so
# Windows tooling such as TestResults behaves consistently on every platform.
TECHNICAL_EXCLUDE_DIRS = frozenset({
    ".ai-task-runner", ".git", ".gradle", ".idea", ".mypy_cache", ".nox",
    ".pytest_cache", ".ruff_cache", ".tox", ".venv", ".vs", ".vscode",
    "__pycache__", "bin", "build", "coverage", "dist", "htmlcov",
    "node_modules", "obj", "target", "testresults",
})
TECHNICAL_EXCLUDE_FILES = frozenset({".coverage", ".ds_store", "thumbs.db"})
TECHNICAL_EXCLUDE_SUFFIXES = frozenset({".pyc", ".pyo"})
# Backwards-compatible public name used by existing tests/extensions.
READONLY_EXCLUDE_DIRS = TECHNICAL_EXCLUDE_DIRS
STALE_TEMP_SECONDS = 7 * 24 * 60 * 60
STALE_TEMP_PREFIXES = ("ai-task-runner-readonly-*", "ai-task-runner-readonly-cache-*", "ai-task-runner-protect-*")


def _key(value: str) -> str:
    return value.casefold()


def is_technical_artifact(path: Path | str, *, is_dir: bool | None = None) -> bool:
    """Return whether one project-relative path is disposable tool/runtime output.

    This intentionally does *not* mean "all dot files". Files such as .gitignore,
    .editorconfig, .env.example, and .github/** remain normal project content.
    """
    value = Path(path)
    parts = value.parts
    if not parts:
        return False
    # Any ignored ancestor makes the complete subtree technical metadata.
    ancestor_parts = parts if is_dir else parts[:-1]
    if any(_key(part) in TECHNICAL_EXCLUDE_DIRS for part in ancestor_parts):
        return True
    name = _key(parts[-1])
    if is_dir is True:
        return name in TECHNICAL_EXCLUDE_DIRS
    if is_dir is False:
        return name in TECHNICAL_EXCLUDE_FILES or Path(name).suffix in TECHNICAL_EXCLUDE_SUFFIXES
    return (
        name in TECHNICAL_EXCLUDE_DIRS
        or name in TECHNICAL_EXCLUDE_FILES
        or Path(name).suffix in TECHNICAL_EXCLUDE_SUFFIXES
    )


def excluded_dirs(root: Path, work: Path) -> set[str]:
    excluded = set(TECHNICAL_EXCLUDE_DIRS)
    if work.is_relative_to(root):
        excluded.add(_key(work.relative_to(root).parts[0]))
    return excluded


def tree_manifest(root: Path, excluded: set[str]) -> dict[str, tuple[str, str | None]]:
    result: dict[str, tuple[str, str | None]] = {}
    excluded_keys = {_key(value) for value in excluded}
    walk_root = io_path(root)
    for current, directories, files in os.walk(walk_root, followlinks=False):
        base = Path(current)
        directories[:] = [name for name in directories if _key(name) not in excluded_keys]
        for name in list(directories):
            path = base / name
            relative = path.relative_to(walk_root).as_posix()
            if path.is_symlink():
                result[relative] = ("link", os.readlink(path))
                directories.remove(name)
            else:
                result[relative] = ("dir", "")
        for name in files:
            if is_technical_artifact(Path(name), is_dir=False):
                continue
            path = base / name
            relative = path.relative_to(walk_root).as_posix()
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
        target_io, source_io = io_path(target), io_path(source)
        if not (target_io.exists() or target_io.is_symlink()) and (source_io.exists() or source_io.is_symlink()):
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
    "READONLY_EXCLUDE_DIRS", "STALE_TEMP_PREFIXES", "STALE_TEMP_SECONDS",
    "TECHNICAL_EXCLUDE_DIRS", "TECHNICAL_EXCLUDE_FILES", "TECHNICAL_EXCLUDE_SUFFIXES",
    "changed_project_files", "cleanup_stale_artifacts", "excluded_dirs",
    "is_technical_artifact", "project_manifest", "restore_project_changes", "tree_manifest",
]
