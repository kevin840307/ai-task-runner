"""Small bounded append helper for diagnostic logs."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MAX_LOG_BYTES = 10 * 1024 * 1024


def append_bounded_log(
    path: Path,
    text: str,
    max_bytes: int = DEFAULT_MAX_LOG_BYTES,
) -> None:
    """Append diagnostic text and retain at most one rotated file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        size = path.stat().st_size if path.exists() else 0
        if size and size + len(text.encode("utf-8")) > max_bytes:
            os.replace(path, path.with_name(path.name + ".1"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
    except OSError:
        pass


__all__ = ["DEFAULT_MAX_LOG_BYTES", "append_bounded_log"]
