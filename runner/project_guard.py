"""Project filesystem protection, snapshots, and read-only model-call helpers."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, Sequence, TypeVar

from .agent import AgentClient
from .errors import RunnerError

T = TypeVar("T")
ProtectedData = bytes | Path | None
READONLY_EXCLUDE_DIRS = frozenset({
    ".git", ".ai-task-runner", ".idea", ".venv", ".vs", "__pycache__",
    "bin", "build", "coverage", "dist", "node_modules", "obj", "target",
})
STALE_TEMP_SECONDS = 7 * 24 * 60 * 60

def runner_source_files() -> list[Path]:
    """Return protected runner source roots (files or directory subtrees)."""
    package_root = Path(__file__).resolve().parent
    root = package_root.parent
    return [
        *(path for name in ("ai_task_runner.py", "ai_task_runner_validator.py")
          if (path := root / name).is_file()),
        package_root,
    ]

def normalize_protected_paths(paths: Sequence[Path]) -> list[Path]:
    """Deduplicate protected roots and drop descendants of an existing root."""
    roots: list[Path] = []
    for path in sorted({Path(value).resolve() for value in paths}, key=lambda p: (len(p.parts), str(p))):
        if not any(path == root or root in path.parents for root in roots):
            roots.append(path)
    return roots

def _directory_digest(path: Path) -> str:
    entries: list[tuple[str, str, str]] = []
    for current, directories, files in os.walk(path, followlinks=False):
        base = Path(current)
        for name in sorted(directories):
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
            if child.is_symlink():
                entries.append((relative, "link", os.readlink(child)))
            else:
                entries.append((
                    relative,
                    "file",
                    hashlib.sha256(child.read_bytes()).hexdigest(),
                ))
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def digest(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        target = os.readlink(path)
        return hashlib.sha256(f"link\0{target}".encode("utf-8")).hexdigest()
    if path.is_dir():
        return _directory_digest(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _snapshot_data(path: Path) -> ProtectedData:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_dir() and not path.is_symlink():
        backup_root = Path(tempfile.mkdtemp(prefix="ai-task-runner-protect-"))
        backup = backup_root / "snapshot"
        shutil.copytree(path, backup, symlinks=True)
        return backup
    return path.read_bytes()

def snapshot(paths: Sequence[Path]) -> dict[Path, tuple[str | None, ProtectedData]]:
    return {path: (digest(path), _snapshot_data(path)) for path in paths}

def restore_changed(
    file_snapshot: dict[Path, tuple[str | None, ProtectedData]],
) -> list[str]:
    """Restore changed protected files or folders and return their paths."""
    changed: list[str] = []
    backup_roots: list[Path] = []
    for path, (old_hash, old_data) in file_snapshot.items():
        if isinstance(old_data, Path):
            backup_roots.append(old_data.parent)
        if digest(path) == old_hash:
            continue
        changed.append(str(path))
        if path.exists() or path.is_symlink():
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        if old_data is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(old_data, Path):
            shutil.copytree(old_data, path, symlinks=True)
        else:
            path.write_bytes(old_data)
    for backup_root in backup_roots:
        shutil.rmtree(backup_root, ignore_errors=True)
    return changed

def changed_snapshot_paths(
    file_snapshot: dict[Path, tuple[str | None, ProtectedData]],
) -> list[str]:
    """Return protected files that differ from a prior snapshot."""
    return [
        str(path)
        for path, (old_hash, _old_data) in file_snapshot.items()
        if digest(path) != old_hash
    ]

def protected_change_detector(
    file_snapshot: dict[Path, tuple[str | None, ProtectedData]],
    change_detected: Callable[[], bool] | None,
) -> Callable[[], bool]:
    def changed() -> bool:
        protected_changed = changed_snapshot_paths(file_snapshot)
        if protected_changed:
            raise RunnerError(
                "protected file modified during model call: "
                + ", ".join(protected_changed)
            )
        return change_detected() if change_detected is not None else False

    return changed

def protected_ask(
    agent: AgentClient,
    prompt: str,
    protected: Sequence[Path],
    idle_timeout_after_change: float = 0,
    change_detected: Callable[[], bool] | None = None,
) -> tuple[str, list[str]]:
    file_snapshot = snapshot(protected)
    output: str | None = None
    try:
        output = agent.ask(
            prompt,
            idle_timeout_after_change,
            protected_change_detector(file_snapshot, change_detected),
        )
    finally:
        changed = restore_changed(file_snapshot)
    return output, changed

def _readonly_excludes(root: Path, work: Path) -> set[str]:
    excluded = set(READONLY_EXCLUDE_DIRS)
    if work.is_relative_to(root):
        excluded.add(work.relative_to(root).parts[0])
    return excluded

def _tree_manifest(
    root: Path,
    excluded_dirs: set[str],
) -> dict[str, tuple[str, str | None]]:
    result: dict[str, tuple[str, str | None]] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = [
            name for name in directories if name not in excluded_dirs
        ]
        for name in list(directories):
            path = base / name
            relative_path = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative_path] = ("link", os.readlink(path))
                directories.remove(name)
            else:
                result[relative_path] = ("dir", "")
        for name in files:
            path = base / name
            relative_path = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative_path] = ("link", os.readlink(path))
            else:
                result[relative_path] = ("file", digest(path))
    return result

def project_manifest(root: Path, work: Path) -> dict[str, tuple[str, str | None]]:
    return _tree_manifest(root, _readonly_excludes(root, work))

def changed_project_files(
    root: Path,
    work: Path,
    before: dict[str, tuple[str, str | None]],
) -> list[str]:
    after = project_manifest(root, work)
    changed = []
    for path in set(before) | set(after):
        if before.get(path) == after.get(path):
            continue
        old_kind = before.get(path, (None, None))[0]
        new_kind = after.get(path, (None, None))[0]
        if old_kind == "dir" or new_kind == "dir":
            continue
        changed.append(path)
    return sorted(changed)

def project_fingerprint(root: Path, work: Path) -> str:
    manifest = _tree_manifest(root, _readonly_excludes(root, work))
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def progress_key(
    root: Path,
    work: Path,
    missing_items: Sequence[str],
) -> str:
    payload = {
        "project": project_fingerprint(root, work),
        "missing_items": list(missing_items),
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)

def _copy_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        target.symlink_to(
            os.readlink(source),
            target_is_directory=source.is_dir(),
        )
    elif source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)

def _restore_project_changes(
    root: Path,
    backup: Path,
    changed: Sequence[str],
) -> None:
    paths = [Path(relative) for relative in changed]
    for relative in sorted(paths, key=lambda value: len(value.parts), reverse=True):
        _remove_path(root / relative)
    for relative in sorted(paths, key=lambda value: len(value.parts)):
        source = backup / relative
        target = root / relative
        if target.exists() or target.is_symlink():
            continue
        if source.exists() or source.is_symlink():
            _copy_path(source, target)

def _copy_ignore(excluded_dirs: set[str]) -> Callable[[str, list[str]], list[str]]:
    def ignore(source: str, names: list[str]) -> list[str]:
        base = Path(source)
        return [
            name
            for name in names
            if name in excluded_dirs and (base / name).is_dir()
        ]

    return ignore

def readonly_project_call(
    action: Callable[[], T],
    root: Path,
    work: Path,
) -> tuple[T, list[str]]:
    """Run an action and restore source changes while ignoring build caches."""
    excluded_dirs = _readonly_excludes(root, work)
    before = _tree_manifest(root, excluded_dirs)
    with tempfile.TemporaryDirectory(prefix="ai-task-runner-readonly-") as temp:
        backup = Path(temp) / "project"
        shutil.copytree(
            root,
            backup,
            symlinks=True,
            ignore=_copy_ignore(excluded_dirs),
        )
        try:
            result = action()
        finally:
            after = _tree_manifest(root, excluded_dirs)
            changed = sorted(
                path
                for path in set(before) | set(after)
                if before.get(path) != after.get(path)
            )
            if changed:
                _restore_project_changes(root, backup, changed)
    return result, changed

def readonly_ask(
    agent: AgentClient,
    prompt: str,
    root: Path,
    work: Path,
    protected: Sequence[Path],
    timeout: int | None = None,
    idle_timeout: float = 0,
) -> tuple[str, list[str], list[str]]:
    file_snapshot = snapshot(protected)
    try:
        output, project_changed = readonly_project_call(
            lambda: agent.ask(
                prompt,
                idle_timeout_after_change=idle_timeout,
                change_detected=lambda: False,
                timeout=timeout,
            ),
            root,
            work,
        )
    finally:
        protected_changed = restore_changed(file_snapshot)
    return output, protected_changed, project_changed


def require_unchanged_project(
    protected_changed: Sequence[str],
    project_changed: Sequence[str],
    actor: str,
) -> None:
    """Reject and report file changes restored after a read-only model call."""
    changed = [*protected_changed, *project_changed]
    if changed:
        raise RunnerError(
            f"{actor} modified files and they were restored: " + ", ".join(changed)
        )

def cleanup_stale_artifacts(
    work: Path,
    temp_root: Path | None = None,
    older_than: float = STALE_TEMP_SECONDS,
) -> None:
    """Remove interrupted atomic writes and old readonly backups."""
    work.mkdir(parents=True, exist_ok=True)
    for path in work.glob("*.tmp"):
        _remove_path(path)

    cutoff = time.time() - older_than
    base = temp_root or Path(tempfile.gettempdir())
    for path in base.glob("ai-task-runner-readonly-*"):
        try:
            if path.stat().st_mtime < cutoff:
                _remove_path(path)
        except OSError:
            continue
