"""Generic project-state snapshots used by recovery and execution boundaries."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path

READONLY_EXCLUDE_DIRS = frozenset({
    ".git", ".ai-task-runner", ".idea", ".venv", ".vs", "__pycache__",
    "bin", "build", "coverage", "dist", "node_modules", "obj", "target",
})
STALE_TEMP_SECONDS = 7 * 24 * 60 * 60


def digest(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        return hashlib.sha256(f"link\0{os.readlink(path)}".encode()).hexdigest()
    if path.is_dir():
        entries: list[tuple[str, str, str]] = []
        for current, directories, files in os.walk(path, followlinks=False):
            base = Path(current)
            for name in sorted(list(directories)):
                child = base / name
                relative = child.relative_to(path).as_posix()
                if child.is_symlink():
                    entries.append((relative, "link", os.readlink(child)))
                    directories.remove(name)
                else:
                    entries.append((relative, "dir", ""))
            for name in sorted(files):
                child = base / name
                relative = child.relative_to(path).as_posix()
                entries.append((
                    relative,
                    "link" if child.is_symlink() else "file",
                    os.readlink(child) if child.is_symlink() else hashlib.sha256(child.read_bytes()).hexdigest(),
                ))
        payload = json.dumps(entries, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def project_fingerprint(root: Path, work: Path) -> str:
    payload = json.dumps(project_manifest(root, work), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def progress_key(root: Path, work: Path, missing_items: Sequence[str]) -> str:
    payload = {"project": project_fingerprint(root, work), "missing_items": list(missing_items)}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def copy_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        target.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
    elif source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)


def restore_project_changes(root: Path, backup: Path, changed: Sequence[str]) -> None:
    paths = [Path(relative) for relative in changed]
    for relative in sorted(paths, key=lambda value: len(value.parts), reverse=True):
        remove_path(root / relative)
    for relative in sorted(paths, key=lambda value: len(value.parts)):
        source, target = backup / relative, root / relative
        if not (target.exists() or target.is_symlink()) and (source.exists() or source.is_symlink()):
            copy_path(source, target)


def copy_ignore(excluded: set[str]) -> Callable[[str, list[str]], list[str]]:
    def ignore(source: str, names: list[str]) -> list[str]:
        base = Path(source)
        return [name for name in names if name in excluded and (base / name).is_dir()]
    return ignore


def cleanup_stale_artifacts(work: Path, temp_root: Path | None = None, older_than: float = STALE_TEMP_SECONDS) -> None:
    work.mkdir(parents=True, exist_ok=True)
    for path in work.glob("*.tmp"):
        remove_path(path)
    cutoff = time.time() - older_than
    for path in (temp_root or Path(tempfile.gettempdir())).glob("ai-task-runner-readonly-*"):
        try:
            if path.stat().st_mtime < cutoff:
                remove_path(path)
        except OSError:
            continue


__all__ = [
    "READONLY_EXCLUDE_DIRS", "STALE_TEMP_SECONDS", "changed_project_files",
    "cleanup_stale_artifacts", "copy_ignore", "digest", "excluded_dirs",
    "progress_key", "project_fingerprint", "project_manifest",
    "restore_project_changes", "tree_manifest",
]
