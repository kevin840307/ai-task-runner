"""Optional loop-context diagnostics and session compression plugin."""
from __future__ import annotations

from collections.abc import Callable

from ..config.defaults import (
    DEFAULT_LOOP_CONTEXT_COMPRESS,
    DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD,
)
from ..config.runtime import is_number

PLUGIN_NAME = "context_compression"


def add_arguments(parser) -> None:
    parser.add_argument(
        "--loop-context-compress",
        action="store_true",
        help="on Loop Detection, compact the session when context usage reaches the threshold",
    )
    parser.add_argument(
        "--loop-context-compress-threshold",
        type=float,
        default=DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD,
        metavar="PERCENT",
        help="context usage percent required for Loop Detection compression (default: 50)",
    )


def config_from_namespace(namespace) -> dict[str, object]:
    return {
        "enabled": namespace.loop_context_compress,
        "threshold": namespace.loop_context_compress_threshold,
    }


def config_from_request(request) -> dict[str, object]:
    return {
        "enabled": request.loop_context_compress,
        "threshold": request.loop_context_compress_threshold,
    }


def config_from_yaml(item) -> dict[str, object]:
    fields = {
        "loop_context_compress": "enabled",
        "loop_context_compress_threshold": "threshold",
    }
    return {target: item[source] for source, target in fields.items() if source in item}


def normalize_config(config) -> dict[str, object]:
    unknown = sorted(set(config) - {"enabled", "threshold"})
    if unknown:
        raise ValueError(f"{PLUGIN_NAME} unknown options: " + ", ".join(unknown))
    enabled = config.get("enabled", DEFAULT_LOOP_CONTEXT_COMPRESS)
    threshold = config.get("threshold", DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD)
    if not isinstance(enabled, bool):
        raise ValueError("loop_context_compress must be a boolean")  # noqa: TRY004
    if not is_number(threshold) or not 0 <= threshold <= 100:
        raise ValueError("loop_context_compress_threshold must be between 0 and 100")
    return {"enabled": enabled, "threshold": float(threshold)}


def _safe_call(action: Callable[[], str]) -> str:
    try:
        return action()
    except Exception as error:  # noqa: BLE001 - diagnostics must not replace the model error
        return f"ERROR: {type(error).__name__}: {error}"


class ContextCompressionPlugin:
    def __init__(self, config) -> None:
        options = normalize_config(config.plugins.get(PLUGIN_NAME, {}))
        self.enabled = options["enabled"]
        self.threshold = options["threshold"]

    def model_error(self, client, error) -> None:
        session = error.session_id or client.session_id
        if not error.diagnostics.get("loop_type") or not session:
            return

        diagnostics = error.diagnostics
        diagnostics.update(
            context_compress_enabled=self.enabled,
            context_compress_threshold=self.threshold,
        )
        snapshot = _safe_call(lambda: client.context_snapshot(session))
        if not snapshot:
            return
        diagnostics["context_snapshot"] = snapshot
        usage = client.context_usage_percent(snapshot)
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
            compression = _safe_call(lambda: client.compress_session(session))
            diagnostics["context_compression"] = compression or "OK"
            diagnostics["context_compress_status"] = (
                "failed" if compression.startswith("ERROR:") else "done"
            )


def register(runtime) -> None:
    runtime.hooks.add(ContextCompressionPlugin(runtime.config))


__all__ = ["PLUGIN_NAME", "ContextCompressionPlugin", "register"]
