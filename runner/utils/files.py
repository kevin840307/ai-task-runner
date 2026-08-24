"""Generic filesystem helpers shared by runtime and plugins."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path


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


def copy_ignore(excluded: set[str]):
    def ignore(source: str, names: list[str]) -> list[str]:
        base = Path(source)
        return [name for name in names if name in excluded and (base / name).is_dir()]
    return ignore
