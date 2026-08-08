"""Best-effort snapshots of the current model prompt and result for local debugging."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .errors import RunnerError


def _write(path: Path, text: str) -> None:
    """Overwrite one debug file without ever affecting runner execution."""
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _header(**values: object) -> str:
    lines = [f"timestamp={datetime.now(timezone.utc).isoformat()}"]
    lines.extend(f"{key}={value}" for key, value in values.items())
    return "\n".join(lines)


def _call_values(backend: str, cwd: Path, session_id: str) -> dict[str, object]:
    return {
        "backend": backend,
        "mode": "resume" if session_id else "new",
        "cwd": cwd,
        "session": session_id or "-",
    }


def _one_line(value: object, limit: int = 1000) -> str:
    return str(value).replace("\r", " ").replace("\n", " ")[-limit:]


def begin_model_call(
    debug_dir: Path | None,
    *,
    backend: str,
    cwd: Path,
    session_id: str,
    prompt: str,
) -> None:
    if debug_dir is None:
        return
    common = {**_call_values(backend, cwd, session_id), "prompt_chars": len(prompt)}
    _write(
        debug_dir / "current-prompt.txt",
        _header(**common) + "\n\n--- PROMPT ---\n\n" + prompt,
    )


def finish_model_call(
    debug_dir: Path | None,
    *,
    backend: str,
    cwd: Path,
    session_id: str,
    prompt: str,
    result: str,
    error: str = "",
) -> None:
    if debug_dir is None:
        return
    values = {
        **_call_values(backend, cwd, session_id),
        "status": "error" if error else "completed",
        "result_chars": len(result),
    }
    values["prompt_chars"] = len(prompt)
    if error:
        values["error"] = _one_line(error)
    _write(
        debug_dir / "last-prompt.txt",
        _header(**values) + "\n\n--- PROMPT ---\n\n" + prompt,
    )
    _write(
        debug_dir / "last-result.txt",
        _header(**values) + "\n\n--- RESULT ---\n\n" + result,
    )


def note_parse_error(debug_dir: Path | None, error: BaseException) -> None:
    """Attach parser/schema failure metadata while preserving the current result body."""
    if debug_dir is None:
        return
    path = debug_dir / "last-result.txt"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    marker = "\n\n--- RESULT ---\n\n"
    head, separator, body = text.partition(marker)
    if not separator:
        return
    lines = [line for line in head.splitlines() if not line.startswith("parse_error=")]
    lines.append(f"parse_error={_one_line(error)}")
    _write(path, "\n".join(lines) + marker + body)


def parse_with_debug(
    debug_dir: Path | None,
    parser: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run a strict model-result parser and record only its failure metadata."""
    try:
        return parser(*args, **kwargs)
    except RunnerError as error:
        note_parse_error(debug_dir, error)
        raise


__all__ = [
    "begin_model_call",
    "finish_model_call",
    "note_parse_error",
    "parse_with_debug",
]
