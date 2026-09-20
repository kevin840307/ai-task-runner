"""AI session and transient-service classification."""
from __future__ import annotations

SESSION_INVALID_MARKERS = (
    "session not found", "session expired", "invalid session", "cannot resume session",
    "failed to resume session", "unknown session",
)
SESSION_RESET_MARKERS = ("loop detection halted the run",)
TRANSIENT_SERVICE_MARKERS = (
    "connection", "rate limit", "too many requests",
    "service unavailable", "bad gateway", "gateway timeout", "http 429", "http 502",
    "http 503", "http 504",
)
DETERMINISTIC_SERVICE_MARKERS = (
    "dockerdesktoplinuxengine",
    "failed to connect to the docker api",
    "failed to obtain sandbox image",
    "sandbox image",
    "failed to relaunch the cli process",
)


def is_session_invalid_error(message: str) -> bool:
    text = message.lower()
    return any(marker in text for marker in SESSION_INVALID_MARKERS)


def is_transient_service_error(message: str) -> bool:
    text = message.lower()
    if "idle timed out" in text:
        return False
    if any(marker in text for marker in DETERMINISTIC_SERVICE_MARKERS):
        return False
    return any(marker in text for marker in TRANSIENT_SERVICE_MARKERS)


def should_reset_session(message: str) -> bool:
    text = message.lower()
    return any(marker in text for marker in SESSION_RESET_MARKERS)


__all__ = ["DETERMINISTIC_SERVICE_MARKERS", "SESSION_INVALID_MARKERS", "SESSION_RESET_MARKERS", "TRANSIENT_SERVICE_MARKERS", "is_session_invalid_error", "is_transient_service_error", "should_reset_session"]
