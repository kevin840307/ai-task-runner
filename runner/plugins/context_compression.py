"""Optional loop-context diagnostics and session compression plugin."""
from __future__ import annotations

from collections.abc import Callable


def _safe_call(action: Callable[[], str]) -> str:
    try:
        return action()
    except Exception as error:  # noqa: BLE001 - diagnostics must not replace the model error
        return f"ERROR: {type(error).__name__}: {error}"


class ContextCompressionPlugin:
    def __init__(self, config) -> None:
        self.enabled = config.loop_context_compress
        self.threshold = float(config.loop_context_compress_threshold)

    def model_error(self, client, error) -> None:
        session = error.session_id or client.session_id
        if not error.diagnostics.get("loop_type") or not session:
            return

        diagnostics = error.diagnostics
        diagnostics.update(
            context_compress_enabled=self.enabled,
            context_compress_threshold=self.threshold,
        )
        snapshot = _safe_call(lambda: client._backend.context_snapshot(session))
        if not snapshot:
            return
        diagnostics["context_snapshot"] = snapshot
        usage = client._backend.context_usage_percent(snapshot)
        if usage is None:
            diagnostics.update(
                context_compress_status="skipped",
                context_compress_reason="context_usage_unknown",
            )
            return

        diagnostics["context_used_percent"] = usage
        if not self.enabled:
            diagnostics.update(
                context_compress_status="skipped",
                context_compress_reason="disabled",
            )
        elif usage < self.threshold:
            diagnostics.update(
                context_compress_status="skipped",
                context_compress_reason="below_threshold",
            )
        else:
            compression = _safe_call(lambda: client._backend.compress_session(session))
            diagnostics["context_compression"] = compression or "OK"
            diagnostics["context_compress_status"] = (
                "failed" if compression.startswith("ERROR:") else "done"
            )


def register(runtime) -> None:
    runtime.hooks.add(ContextCompressionPlugin(runtime.config))


__all__ = ["ContextCompressionPlugin", "register"]
