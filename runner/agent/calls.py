"""Backward-compatible retry API; new code imports runner.agent.retry."""
from __future__ import annotations

from .retry import recover_structured_output
from . import retry as _retry


def retry_model_call(action, *args, **kwargs):
    # Legacy callers passed a UI object before status/detail. Ignore it because
    # runtime status observers now own UI/observability.
    if args and not isinstance(args[0], str):
        args = args[1:]
    return _retry.retry_model_call(action, *args, **kwargs)


__all__ = ["recover_structured_output", "retry_model_call"]
