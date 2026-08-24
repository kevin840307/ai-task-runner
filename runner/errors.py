"""Runner error types and shared error-chain diagnostics."""
from __future__ import annotations


class RunnerError(RuntimeError):
    """Recoverable orchestration failure."""


class ConfigurationError(RunnerError):
    """Deterministic input or configuration failure that retrying cannot fix."""


class StructuredOutputError(RunnerError):
    """Structured response recovery was exhausted inside one AI stage call."""


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


def backend_diagnostic_parts(
    error: BaseException,
    *,
    include_output: bool = False,
) -> list[str]:
    """Return normalized backend metadata from a wrapped error chain."""
    parts: list[str] = []
    cause = diagnostic_error(error)
    if cause is None:
        return parts

    return_code = getattr(cause, "return_code", None)
    if return_code is not None:
        parts.append(f"exit_code={return_code}")
    elapsed = getattr(cause, "elapsed", 0.0)
    if elapsed:
        parts.append(f"elapsed_seconds={elapsed:.1f}")
    command_mode = getattr(cause, "command_mode", "")
    if command_mode:
        parts.append(f"command_mode={command_mode}")
    source_event = getattr(cause, "session_source_event", "")
    if source_event:
        parts.append(f"session_source_event={source_event}")

    diagnostics = getattr(cause, "diagnostics", {})
    if diagnostics:
        for name in (
            "loop_type",
            "session_recovery_action",
            "num_turns",
            "context_used_percent",
            "context_compress_enabled",
            "context_compress_threshold",
            "context_compress_status",
            "context_compress_reason",
            "input_tokens",
            "cache_read_input_tokens",
            "output_tokens",
            "total_tokens",
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
            parts.append(
                "context_snapshot=" + " ".join(str(snapshot).split())[-2000:]
            )
        compression = diagnostics.get("context_compression")
        if compression:
            parts.append(
                "context_compression=" + " ".join(str(compression).split())[-1000:]
            )
        plugin_error = diagnostics.get("plugin_error")
        if plugin_error:
            parts.append("plugin_error=" + " ".join(str(plugin_error).split())[-1000:])

    if include_output:
        output = getattr(cause, "output", "")
        if output:
            parts.append("stderr_tail=" + " ".join(str(output).split())[-1000:])
    return parts


def diagnostic_detail(error: BaseException, limit: int = 2000) -> str:
    """Format existing backend diagnostics for logs without changing recovery behavior."""
    parts = [str(error), *backend_diagnostic_parts(error)]
    return " | ".join(parts)[-limit:]


__all__ = [
    "RunnerError",
    "StructuredOutputError",
    "backend_diagnostic_parts",
    "diagnostic_detail",
    "diagnostic_error",
]
