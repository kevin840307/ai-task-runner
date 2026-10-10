"""Small cross-domain filesystem, log, and text helpers."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from project_registry import path_key

DEFAULT_MAX_LOG_BYTES = 10 * 1024 * 1024


def _windows_extended_path(path: Path | str) -> Path:
    value = Path(path)
    if os.name != "nt" or not value.is_absolute():
        return value
    text = str(value)
    if text.startswith("\\\\?\\"):
        return value
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


def io_path(path: Path | str) -> Path:
    value = Path(path)
    if os.name != "nt":
        return value
    text = str(value)
    if text.startswith("\\\\?\\") or not value.is_absolute() or len(text) < 240:
        return value
    return _windows_extended_path(value)


def same_path(left: Path | str, right: Path | str) -> bool:
    return path_key(left) == path_key(right)


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
                    os.readlink(child)
                    if child.is_symlink()
                    else hashlib.sha256(child.read_bytes()).hexdigest(),
                ))
        payload = json.dumps(entries, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()
    return hashlib.sha256(source.read_bytes()).hexdigest()


def remove_path(path: Path) -> None:
    logical = Path(path)
    value = io_path(logical)
    if value.is_symlink() or value.is_file():
        value.unlink(missing_ok=True)
        return
    tree = _windows_extended_path(logical.absolute()) if os.name == "nt" else value
    if tree.exists():
        shutil.rmtree(tree)


def copy_path(source: Path, target: Path) -> None:
    source_io, target_io = io_path(source), io_path(target)
    io_path(Path(target).parent).mkdir(parents=True, exist_ok=True)
    if source_io.is_symlink():
        target_io.symlink_to(
            os.readlink(source_io),
            target_is_directory=source_io.is_dir(),
        )
    elif source_io.is_dir():
        shutil.copytree(source_io, target_io, symlinks=True)
    else:
        shutil.copy2(source_io, target_io)


def copy_ignore(excluded: set[str]):
    excluded_keys = {name.casefold() for name in excluded}

    def ignore(source: str, names: list[str]) -> list[str]:
        base = Path(source)
        return [
            name
            for name in names
            if name.casefold() in excluded_keys and (base / name).is_dir()
        ]

    return ignore


def atomic_write_text(path: Path, text: str) -> None:
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


def append_bounded_log(
    path: Path,
    text: str,
    max_bytes: int = DEFAULT_MAX_LOG_BYTES,
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        limit = max(0, int(max_bytes))
        if limit == 0:
            return

        payload = text.encode("utf-8")
        if len(payload) > limit:
            if path.exists():
                os.replace(path, path.with_name(path.name + ".1"))
            # Keep the newest diagnostic bytes; ignore only a possible partial
            # UTF-8 codepoint at the truncation boundary.
            text = payload[-limit:].decode("utf-8", errors="ignore")
            path.write_text(text, encoding="utf-8")
            return

        size = path.stat().st_size if path.exists() else 0
        if size and size + len(payload) > limit:
            os.replace(path, path.with_name(path.name + ".1"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
    except OSError:
        pass


def bounded_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit < 100:
        return text[-limit:]
    head = limit // 2
    marker = f"\n... omitted {len(text) - limit} characters ...\n"
    tail = max(0, limit - head - len(marker))
    return text[:head] + marker + text[-tail:]


__all__ = [
    "DEFAULT_MAX_LOG_BYTES",
    "append_bounded_log",
    "atomic_write_text",
    "bounded_text",
    "copy_ignore",
    "copy_path",
    "digest",
    "io_path",
    "path_key",
    "remove_path",
    "same_path",
]
