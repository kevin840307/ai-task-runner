"""Loop/context diagnostics used by AIClient; no workflow policy lives here."""
from __future__ import annotations

from .errors import BackendError
from .session import should_reset_session


def prepare_session_recovery(client, error: BackendError, message: str) -> None:
    diagnostics = error.diagnostics
    if not (diagnostics.get("loop_type") or should_reset_session(message)):
        return
    try:
        from ..bootstrap import current_runtime
        current_runtime().hooks.model_error(client, error)
    except RuntimeError:
        pass
    diagnostics["session_recovery_action"] = (
        "compress_and_retry" if diagnostics.get("context_compress_status") == "done" else "stage_executor_retry"
    )


def error_result(backend, error: BackendError) -> str:
    if not error.output:
        return ""
    try:
        return backend.decode(error.output).text
    except Exception:
        return error.output[-20_000:]


__all__ = ["error_result", "prepare_session_recovery"]
