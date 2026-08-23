"""Generic model-call retry and structured-output recovery helpers."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from ..errors import RunnerError, diagnostic_detail
from ..app.ui import LiveUI

T = TypeVar("T")

def recover_structured_output(
    raw: str,
    parse: Callable[[str], T],
    correct: Callable[[str], str],
    retries: int = 1,
) -> T:
    """Retry only malformed structured output in the same live model session."""
    error: RunnerError | None = None
    for attempt in range(retries + 1):
        try:
            return parse(raw)
        except RunnerError as current:
            error = current
            if attempt >= retries:
                raise
            raw = correct(str(current))
    assert error is not None
    raise error

def retry_model_call(
    action: Callable[[], T],
    ui: LiveUI,
    status: str,
    detail: str,
    wait: float,
    max_wait: float,
    max_errors: int = 0,
    max_attempts: int = 0,
) -> T:
    delay = max(0.0, wait)
    errors = 0
    attempts = 0
    while True:
        attempts += 1
        ui.start(status, detail)
        try:
            return action()
        except RunnerError as error:
            transient = bool(getattr(error, "transient", False))
            if not transient:
                errors += 1
            ui.stop("模型呼叫異常，將自動重試", diagnostic_detail(error))
            limit_reached = (
                max_attempts and attempts >= max_attempts
            ) or (
                not transient and max_errors and errors >= max_errors
            )
            if limit_reached:
                raise RunnerError(
                    f"model call failed after {attempts} attempt(s); "
                    "retrying from the runner task flow: "
                    f"{str(error)[-1000:]}"
                ) from error
            if delay:
                time.sleep(delay)
                delay = min(max_wait, max(wait, delay * 2))
        finally:
            ui.stop()


__all__ = ["recover_structured_output", "retry_model_call"]
