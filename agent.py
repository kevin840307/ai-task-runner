"""Session-aware facade over a registered backend."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from backends import BackendError, create_backend
from errors import RunnerError


SESSION_INVALID_MARKERS = (
    "session not found",
    "session expired",
    "invalid session",
    "cannot resume session",
    "failed to resume session",
    "unknown session",
    "loop detection halted the run",
)


def is_session_invalid_error(message: str) -> bool:
    text = message.lower()
    return any(marker in text for marker in SESSION_INVALID_MARKERS)


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

    @property
    def name(self) -> str:
        return self.backend

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
        try:
            result = self._backend.ask(
                prompt,
                self.session_id,
                idle_timeout_after_change,
                change_detected,
            )
        except BackendError as error:
            message = str(error)
            if self.session_id and is_session_invalid_error(message):
                expired_session = self.session_id
                self.session_id = ""
                raise AgentError(
                    f"session {expired_session} is unavailable; "
                    "a new session will continue from runner state"
                ) from error
            raise AgentError(message) from error
        finally:
            self.timeout = previous_timeout
            self._backend.timeout = previous_backend_timeout
        if result.session_id and not self.session_id:
            self.session_id = result.session_id
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

__all__ = ["AgentClient", "Agent", "AgentError", "is_session_invalid_error"]
