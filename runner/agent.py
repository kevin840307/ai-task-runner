"""Session-aware facade over a registered backend."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, NoReturn, Sequence

from runner.backends import BackendError, create_backend
from runner.defaults import DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD
from .debug import begin_model_call, finish_model_call
from .errors import RunnerError, diagnostic_detail


SESSION_INVALID_MARKERS = (
    "session not found",
    "session expired",
    "invalid session",
    "cannot resume session",
    "failed to resume session",
    "unknown session",
)
SESSION_RESET_MARKERS = (
    "loop detection halted the run",
)
SESSION_RECOVERABLE_FAILURES_BEFORE_RESET = 2
TRANSIENT_SERVICE_MARKERS = (
    "timed out",
    "timeout",
    "connection",
    "rate limit",
    "too many requests",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "http 429",
    "http 502",
    "http 503",
    "http 504",
)


def is_session_invalid_error(message: str) -> bool:
    text = message.lower()
    return any(marker in text for marker in SESSION_INVALID_MARKERS)



def is_transient_service_error(message: str) -> bool:
    text = message.lower()
    if "idle timed out" in text:
        return False
    return any(marker in text for marker in TRANSIENT_SERVICE_MARKERS)

def should_reset_session(message: str) -> bool:
    text = message.lower()
    return any(marker in text for marker in SESSION_RESET_MARKERS)


class AgentError(RunnerError):
    """Raised when an AI backend call fails."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class AgentClient:
    def __init__(
        self,
        backend: str,
        command: str | None,
        root: Path,
        extra_args: Sequence[str],
        session_id: str = "",
        timeout: int = 7200,
        debug_dir: Path | None = None,
        loop_context_compress: bool = False,
        loop_context_compress_threshold: float = DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD,
    ) -> None:
        try:
            self._backend = create_backend(
                backend, command, root, extra_args, timeout
            )
        except BackendError as error:
            raise AgentError(str(error), transient=is_transient_service_error(str(error))) from error

        # Preserve the simple public attributes from the original single-file Agent.
        self.backend = self._backend.name
        self.base_command = self._backend.base_command
        self.root = self._backend.root
        self.extra_args = self._backend.extra_args
        self.session_id = session_id
        self.timeout = timeout
        self.debug_dir = debug_dir
        self._recoverable_session_failures = 0
        self.loop_context_compress = loop_context_compress
        self.loop_context_compress_threshold = loop_context_compress_threshold

    @property
    def name(self) -> str:
        return self.backend

    def set_extra_args(self, extra_args: Sequence[str]) -> None:
        """Switch stage capabilities without replacing this client or session."""
        values = list(extra_args)
        self.extra_args = values
        self._backend.extra_args = values

    def _finish_debug(
        self,
        session_id: str,
        prompt: str,
        result: str,
        call_id: str,
        error: str = "",
    ) -> None:
        finish_model_call(
            getattr(self, "debug_dir", None),
            backend=self.backend,
            cwd=self.root,
            session_id=session_id,
            prompt=prompt,
            result=result,
            call_id=call_id,
            error=error,
        )

    @staticmethod
    def _diagnostic_call(action: Callable[[], str]) -> str:
        """Keep optional backend diagnostics from replacing the real failure."""
        try:
            return action()
        except Exception as error:
            return f"ERROR: {type(error).__name__}: {error}"

    def _enrich_loop_diagnostics(self, error: BackendError) -> None:
        snapshot_session = error.session_id or self.session_id
        if not error.diagnostics.get("loop_type") or not snapshot_session:
            return

        snapshot = self._diagnostic_call(
            lambda: self._backend.context_snapshot(snapshot_session)
        )
        if not snapshot:
            return

        diagnostics = error.diagnostics
        diagnostics["context_snapshot"] = snapshot
        enabled = bool(getattr(self, "loop_context_compress", False))
        threshold = float(
            getattr(
                self,
                "loop_context_compress_threshold",
                DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD,
            )
        )
        diagnostics["context_compress_enabled"] = enabled
        diagnostics["context_compress_threshold"] = threshold
        usage = self._backend.context_usage_percent(snapshot)
        if usage is None:
            diagnostics["context_compress_status"] = "skipped"
            diagnostics["context_compress_reason"] = "context_usage_unknown"
            return

        diagnostics["context_used_percent"] = usage
        if not enabled:
            diagnostics["context_compress_status"] = "skipped"
            diagnostics["context_compress_reason"] = "disabled"
        elif usage < threshold:
            diagnostics["context_compress_status"] = "skipped"
            diagnostics["context_compress_reason"] = "below_threshold"
        else:
            diagnostics["context_compress_status"] = "started"
            compression = self._diagnostic_call(
                lambda: self._backend.compress_session(snapshot_session)
            )
            diagnostics["context_compression"] = compression or "OK"
            diagnostics["context_compress_status"] = (
                "failed" if compression.startswith("ERROR:") else "done"
            )

    def _error_result(self, error: BackendError) -> str:
        if not error.output:
            return ""
        try:
            return self._backend.decode(error.output).text
        except Exception:
            return error.output[-20_000:]

    def _raise_backend_error(
        self,
        error: BackendError,
        prompt: str,
        call_session_id: str,
        debug_call_id: str,
    ) -> NoReturn:
        self._enrich_loop_diagnostics(error)
        self._finish_debug(
            call_session_id,
            prompt,
            self._error_result(error),
            debug_call_id,
            diagnostic_detail(error),
        )
        if error.session_id and not self.session_id:
            self.session_id = error.session_id

        message = str(error)
        if self.session_id and is_session_invalid_error(message):
            expired_session = self.session_id
            self.session_id = ""
            raise AgentError(
                f"session {expired_session} is unavailable; "
                "a new session will continue from runner state"
            ) from error

        if self.session_id and should_reset_session(message):
            failures = getattr(self, "_recoverable_session_failures", 0) + 1
            self._recoverable_session_failures = failures
            if failures >= SESSION_RECOVERABLE_FAILURES_BEFORE_RESET:
                self.session_id = ""
                self._recoverable_session_failures = 0
        else:
            self._recoverable_session_failures = 0
        raise AgentError(
            message,
            transient=is_transient_service_error(message),
        ) from error

    def ask(
        self,
        prompt: str,
        idle_timeout_after_change: float = 0,
        change_detected: Callable[[], bool] | None = None,
        timeout: int | None = None,
    ) -> str:
        previous_timeout = self.timeout
        previous_backend_timeout = self._backend.timeout
        if timeout is not None:
            self.timeout = timeout
            self._backend.timeout = timeout
        call_session_id = self.session_id
        debug_call_id = begin_model_call(
            getattr(self, "debug_dir", None),
            backend=self.backend,
            cwd=self.root,
            session_id=call_session_id,
            prompt=prompt,
        )
        try:
            result = self._backend.ask(
                prompt,
                self.session_id,
                idle_timeout_after_change,
                change_detected,
            )
        except BackendError as error:
            self._raise_backend_error(
                error,
                prompt,
                call_session_id,
                debug_call_id,
            )
        finally:
            self.timeout = previous_timeout
            self._backend.timeout = previous_backend_timeout
        if result.session_id and not self.session_id:
            self.session_id = result.session_id
        self._recoverable_session_failures = 0
        self._finish_debug(call_session_id, prompt, result.text, debug_call_id)
        return result.text

    def prepare_project(self) -> list[Path]:
        return self._backend.prepare_project()

    def update_goal_reference(self, goal_file: str | None) -> None:
        self._backend.update_goal_reference(goal_file)

    def _build_command(self, prompt: str) -> list[str]:
        """Compatibility delegate for existing integrations/tests."""
        return self._backend.build_command(prompt, self.session_id)

    def _decode(self, raw: str) -> str:
        """Compatibility delegate for existing integrations/tests."""
        result = self._backend.decode(raw)
        if result.session_id and not self.session_id:
            self.session_id = result.session_id
        return result.text


# Backward-compatible alias used by releases before v1.0.
Agent = AgentClient

__all__ = [
    "AgentClient",
    "Agent",
    "AgentError",
    "SESSION_INVALID_MARKERS",
    "SESSION_RESET_MARKERS",
    "SESSION_RECOVERABLE_FAILURES_BEFORE_RESET",
    "TRANSIENT_SERVICE_MARKERS",
    "is_session_invalid_error",
    "is_transient_service_error",
    "should_reset_session",
]
