"""Generic filesystem helpers shared by runtime and plugins."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

def io_path(path: Path | str) -> Path:
    """Return a Windows extended-length path when normal MAX_PATH handling is risky.

    The caller keeps using the original logical Path for containment/relative checks;
    this helper is only for filesystem I/O. On non-Windows platforms it is a no-op.
    """
    value = Path(path)
    if os.name != "nt":
        return value
    text = str(value)
    if text.startswith("\\\\?\\") or not value.is_absolute():
        return value
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


def _exists(path: Path) -> bool:
    value = io_path(path)
    return value.exists() or value.is_symlink()


def digest(path: Path) -> str | None:
    logical = Path(path)
    source = io_path(logical)
    if not source.exists() and not source.is_symlink():
        return None
    if source.is_symlink():
        return hashlib.sha256(f"link\0{os.readlink(source)}".encode()).hexdigest()
    if source.is_dir():
        entries: list[tuple[str, str, str]] = []
        walk_root = source
        for current, directories, files in os.walk(walk_root, followlinks=False):
            base = Path(current)
            for name in sorted(list(directories)):
                child = base / name
                relative = child.relative_to(walk_root).as_posix()
                if child.is_symlink():
                    entries.append((relative, "link", os.readlink(child)))
                    directories.remove(name)
                else:
                    entries.append((relative, "dir", ""))
            for name in sorted(files):
                child = base / name
                relative = child.relative_to(walk_root).as_posix()
                entries.append((
                    relative,
                    "link" if child.is_symlink() else "file",
                    os.readlink(child) if child.is_symlink() else hashlib.sha256(child.read_bytes()).hexdigest(),
                ))
        payload = json.dumps(entries, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()
    return hashlib.sha256(source.read_bytes()).hexdigest()


def remove_path(path: Path) -> None:
    value = io_path(path)
    if value.is_symlink() or value.is_file():
        value.unlink(missing_ok=True)
    elif value.exists():
        shutil.rmtree(value)


def copy_path(source: Path, target: Path) -> None:
    source_io, target_io = io_path(source), io_path(target)
    target_parent = io_path(Path(target).parent)
    target_parent.mkdir(parents=True, exist_ok=True)
    if source_io.is_symlink():
        target_io.symlink_to(os.readlink(source_io), target_is_directory=source_io.is_dir())
    elif source_io.is_dir():
        shutil.copytree(source_io, target_io, symlinks=True)
    else:
        shutil.copy2(source_io, target_io)


def copy_ignore(excluded: set[str]):
    def ignore(source: str, names: list[str]) -> list[str]:
        base = Path(source)
        return [name for name in names if name in excluded and (base / name).is_dir()]
    return ignore


def atomic_write_text(path: Path, text: str) -> None:
    """Best-effort atomic UTF-8 text write for non-durable plugin snapshots."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        io_path(path.parent).mkdir(parents=True, exist_ok=True)
        io_path(temporary).write_text(text, encoding="utf-8")
        os.replace(io_path(temporary), io_path(path))
    except OSError:
        try:
            io_path(temporary).unlink(missing_ok=True)
        except OSError:
            pass


__all__ = ["atomic_write_text", "copy_ignore", "copy_path", "digest", "io_path", "remove_path"]
