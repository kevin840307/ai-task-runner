"""Best-effort snapshots of the current model prompt and result for local debugging."""
from __future__ import annotations

import os
from itertools import count
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..errors import RunnerError


_HISTORY_MAX_CALLS = 100
_HISTORY_MAX_BYTES = 50 * 1024 * 1024
_HISTORY_MAX_ENTRY_BYTES = 2 * 1024 * 1024
_HISTORY_SEQUENCE = count(1)


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


def _bounded_text(text: str, max_bytes: int | None = None) -> str:
    max_bytes = _HISTORY_MAX_ENTRY_BYTES if max_bytes is None else max_bytes
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    marker = f"\n\n--- TRUNCATED: original_bytes={len(data)} ---\n\n".encode("utf-8")
    budget = max(0, max_bytes - len(marker))
    head = budget // 2
    tail = budget - head
    return (data[:head] + marker + data[-tail:]).decode("utf-8", errors="replace")


def _history_pairs(history: Path) -> list[tuple[str, list[Path]]]:
    grouped: dict[str, list[Path]] = {}
    try:
        files = list(history.glob("*.txt"))
    except OSError:
        return []
    for path in files:
        name = path.name
        for suffix in ("-prompt.txt", "-result.txt"):
            if name.endswith(suffix):
                grouped.setdefault(name[: -len(suffix)], []).append(path)
                break
    return sorted(grouped.items())


def _trim_history(history: Path) -> None:
    pairs = _history_pairs(history)
    def total_bytes() -> int:
        total = 0
        for _, files in pairs:
            for path in files:
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
        return total

    size = total_bytes()
    while pairs and (len(pairs) > _HISTORY_MAX_CALLS or size > _HISTORY_MAX_BYTES):
        _, files = pairs.pop(0)
        for path in files:
            try:
                size -= path.stat().st_size
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _new_call_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + f"-{next(_HISTORY_SEQUENCE):06d}"


def _write_history_prompt(debug_dir: Path, call_id: str, prompt_text: str) -> None:
    history = debug_dir / "history"
    _write(history / f"{call_id}-prompt.txt", _bounded_text(prompt_text))
    _trim_history(history)


def _write_history_result(debug_dir: Path, call_id: str, result_text: str) -> None:
    history = debug_dir / "history"
    _write(history / f"{call_id}-result.txt", _bounded_text(result_text))
    _trim_history(history)


def begin_model_call(
    debug_dir: Path | None,
    *,
    backend: str,
    cwd: Path,
    session_id: str,
    prompt: str,
) -> str:
    call_id = _new_call_id()
    if debug_dir is None:
        return call_id
    common = {**_call_values(backend, cwd, session_id), "prompt_chars": len(prompt)}
    prompt_text = _header(**common) + "\n\n--- PROMPT ---\n\n" + prompt
    _write(debug_dir / "current-prompt.txt", prompt_text)
    _write_history_prompt(debug_dir, call_id, prompt_text)
    return call_id


def finish_model_call(
    debug_dir: Path | None,
    *,
    backend: str,
    cwd: Path,
    session_id: str,
    prompt: str,
    result: str,
    call_id: str,
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
    prompt_text = _header(**values) + "\n\n--- PROMPT ---\n\n" + prompt
    result_text = _header(**values) + "\n\n--- RESULT ---\n\n" + result
    _write(debug_dir / "last-prompt.txt", prompt_text)
    _write(debug_dir / "last-result.txt", result_text)
    _write_history_result(debug_dir, call_id, result_text)


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
    updated = "\n".join(lines) + marker + body
    _write(path, updated)
    pairs = _history_pairs(debug_dir / "history")
    if pairs:
        result_path = debug_dir / "history" / f"{pairs[-1][0]}-result.txt"
        if result_path.exists():
            _write(result_path, _bounded_text(updated))


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
