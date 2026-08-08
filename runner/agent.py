"""Session-aware facade over a registered backend."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from runner.backends import BackendError, create_backend
from .debug import begin_model_call, finish_model_call
from .errors import RunnerError


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


def is_session_invalid_error(message: str) -> bool:
    text = message.lower()
    return any(marker in text for marker in SESSION_INVALID_MARKERS)


def should_reset_session(message: str) -> bool:
    text = message.lower()
    return any(marker in text for marker in SESSION_RESET_MARKERS)


class AgentError(RunnerError):
    """Raised when an AI backend call fails."""


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
    ) -> None:
        try:
            self._backend = create_backend(
                backend, command, root, extra_args, timeout
            )
        except BackendError as error:
            raise AgentError(str(error)) from error

        # Preserve the simple public attributes from the original single-file Agent.
        self.backend = self._backend.name
        self.base_command = self._backend.base_command
        self.root = self._backend.root
        self.extra_args = self._backend.extra_args
        self.session_id = session_id
        self.timeout = timeout
        self.debug_dir = debug_dir

    @property
    def name(self) -> str:
        return self.backend

    def _finish_debug(
        self,
        session_id: str,
        prompt: str,
        result: str,
        error: str = "",
    ) -> None:
        finish_model_call(
            getattr(self, "debug_dir", None),
            backend=self.backend,
            cwd=self.root,
            session_id=session_id,
            prompt=prompt,
            result=result,
            error=error,
        )

    def ask(
        self,
        prompt: str,
        idle_timeout_after_change: float = 0,
        change_detected: Callable[[], bool] | None = None,
        timeout: int | None = None,
        preserve_session_on_error: bool = False,
    ) -> str:
        previous_timeout = self.timeout
        previous_backend_timeout = self._backend.timeout
        if timeout is not None:
            self.timeout = timeout
            self._backend.timeout = timeout
        call_session_id = self.session_id
        begin_model_call(
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
            error_result = ""
            if error.output:
                try:
                    error_result = self._backend.decode(error.output).text
                except Exception:
                    error_result = error.output[-20_000:]
            self._finish_debug(call_session_id, prompt, error_result, str(error))
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
            if (
                self.session_id
                and should_reset_session(message)
                and not preserve_session_on_error
            ):
                self.session_id = ""
            raise AgentError(message) from error
        finally:
            self.timeout = previous_timeout
            self._backend.timeout = previous_backend_timeout
        if result.session_id and not self.session_id:
            self.session_id = result.session_id
        self._finish_debug(call_session_id, prompt, result.text)
        return result.text

    def prepare_project(self) -> list[Path]:
        return self._backend.prepare_project()

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
    "is_session_invalid_error",
    "should_reset_session",
]
