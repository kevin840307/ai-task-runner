"""Runner error types and shared error-chain diagnostics."""
from __future__ import annotations


class RunnerError(RuntimeError):
    """Recoverable orchestration failure."""


def diagnostic_error(error: BaseException) -> BaseException | None:
    """Find backend diagnostics through wrapped exception chains."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if any(
            hasattr(current, name)
            for name in (
                "return_code",
                "elapsed",
                "output",
                "command_mode",
                "session_source_event",
            )
        ):
            return current
        current = current.__cause__ or current.__context__
    return None


def diagnostic_detail(error: BaseException, limit: int = 2000) -> str:
    """Format existing backend diagnostics for logs without changing recovery behavior."""
    parts = [str(error)]
    cause = diagnostic_error(error)
    diagnostics = getattr(cause, "diagnostics", {}) if cause is not None else {}
    if diagnostics:
        for name in (
            "loop_type", "num_turns", "input_tokens", "context_used_percent",
            "cache_read_input_tokens", "output_tokens", "total_tokens",
        ):
            value = diagnostics.get(name)
            if value not in (None, ""):
                parts.append(f"{name}={value}")
        if any(name in diagnostics for name in (
            "input_tokens", "cache_read_input_tokens", "total_tokens"
        )):
            parts.append("token_scope=backend_reported_not_current_context")
        snapshot = diagnostics.get("context_snapshot")
        if snapshot:
            parts.append("context_snapshot=" + " ".join(str(snapshot).split()))
        for name in (
            "context_compress_enabled", "context_compress_threshold",
            "context_compress_status", "context_compress_reason",
        ):
            value = diagnostics.get(name)
            if value not in (None, ""):
                parts.append(f"{name}={value}")
        compression = diagnostics.get("context_compression")
        if compression:
            parts.append("context_compression=" + " ".join(str(compression).split()))
    return " | ".join(parts)[-limit:]


__all__ = ["RunnerError", "diagnostic_error", "diagnostic_detail"]
