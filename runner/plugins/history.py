"""Optional bounded model-call history observer."""
from __future__ import annotations

from pathlib import Path

from ..utils.files import atomic_write_text

_MAX_CALLS = 100
_MAX_BYTES = 50 * 1024 * 1024




def _pairs(history: Path) -> list[tuple[str, list[Path]]]:
    grouped: dict[str, list[Path]] = {}
    try:
        files = list(history.glob("*.txt"))
    except OSError:
        return []
    for path in files:
        for suffix in ("-prompt.txt", "-result.txt"):
            if path.name.endswith(suffix):
                grouped.setdefault(path.name[: -len(suffix)], []).append(path)
                break
    return sorted(grouped.items())


def _trim(history: Path) -> None:
    pairs = _pairs(history)
    size = 0
    for _, files in pairs:
        for path in files:
            try:
                size += path.stat().st_size
            except OSError:
                pass
    while pairs and (len(pairs) > _MAX_CALLS or size > _MAX_BYTES):
        _, files = pairs.pop(0)
        for path in files:
            try:
                size -= path.stat().st_size
                path.unlink(missing_ok=True)
            except OSError:
                pass


class HistoryObserver:
    def __call__(self, event: dict) -> None:
        kind = event.get("type")
        debug_dir = event.get("debug_dir")
        if not debug_dir or kind not in {"model.prompt", "model.result", "model.parse_error"}:
            return
        history = Path(debug_dir) / "history"
        text = str(event.get("text", ""))
        if kind == "model.parse_error":
            pairs = _pairs(history)
            if pairs:
                atomic_write_text(history / f"{pairs[-1][0]}-result.txt", text)
            return
        call_id = str(event.get("call_id", ""))
        if not call_id:
            return
        suffix = "prompt" if kind == "model.prompt" else "result"
        atomic_write_text(history / f"{call_id}-{suffix}.txt", text)
        _trim(history)


def register(runtime) -> None:
    runtime.events.subscribe(HistoryObserver())
