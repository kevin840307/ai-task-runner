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


__all__ = ["RunnerError", "diagnostic_error"]
