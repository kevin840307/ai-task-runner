"""Model and backend errors."""
from __future__ import annotations
from typing import Any
from ..errors import RunnerError

class ModelError(RunnerError):
    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient

class BackendError(RunnerError):
    """Raised when a backend CLI call cannot produce a usable result."""

    def __init__(
        self,
        message: str,
        *,
        session_id: str = "",
        return_code: int | None = None,
        elapsed: float = 0.0,
        output: str = "",
        command_mode: str = "",
        session_source_event: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.session_id = session_id
        self.return_code = return_code
        self.elapsed = elapsed
        self.output = output
        self.command_mode = command_mode
        self.session_source_event = session_source_event
        self.diagnostics = dict(diagnostics or {})


__all__ = ["ModelError", "BackendError"]
