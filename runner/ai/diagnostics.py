"""Loop/context diagnostics used by AIClient; no workflow policy lives here."""
from __future__ import annotations

from collections.abc import Callable

from ..config.defaults import DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD
from .errors import BackendError
from .session import should_reset_session


def safe_call(action: Callable[[], str]) -> str:
    try:
        return action()
    except Exception as error:
        return f"ERROR: {type(error).__name__}: {error}"


def enrich_loop(client, error: BackendError, *, allow_context_recovery: bool = True) -> None:
    session = error.session_id or client.session_id
    if not error.diagnostics.get("loop_type") or not session:
        return

    diagnostics = error.diagnostics
    enabled = bool(getattr(client, "loop_context_compress", False))
    threshold = float(getattr(client, "loop_context_compress_threshold", DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD))
    diagnostics.update(context_compress_enabled=enabled, context_compress_threshold=threshold)
    if not allow_context_recovery:
        diagnostics.update(context_compress_status="skipped", context_compress_reason="session_reset")
        return

    snapshot = safe_call(lambda: client._backend.context_snapshot(session))
    if not snapshot:
        return
    diagnostics["context_snapshot"] = snapshot
    usage = client._backend.context_usage_percent(snapshot)
    if usage is None:
        diagnostics.update(context_compress_status="skipped", context_compress_reason="context_usage_unknown")
        return

    diagnostics["context_used_percent"] = usage
    if not enabled:
        diagnostics.update(context_compress_status="skipped", context_compress_reason="disabled")
    elif usage < threshold:
        diagnostics.update(context_compress_status="skipped", context_compress_reason="below_threshold")
    else:
        diagnostics["context_compress_status"] = "started"
        compression = safe_call(lambda: client._backend.compress_session(session))
        diagnostics["context_compression"] = compression or "OK"
        diagnostics["context_compress_status"] = "failed" if compression.startswith("ERROR:") else "done"


def prepare_session_recovery(client, error: BackendError, message: str) -> None:
    diagnostics = error.diagnostics
    if not (diagnostics.get("loop_type") or should_reset_session(message)):
        return
    enrich_loop(client, error)
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


__all__ = ["enrich_loop", "error_result", "prepare_session_recovery", "safe_call"]
