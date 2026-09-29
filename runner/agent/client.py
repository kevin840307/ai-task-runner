"""AI client, session policy, and model error coordination."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn, Protocol

from ..config.defaults import DEFAULT_AGENT_TIMEOUT
from ..errors import RunnerError, diagnostic_detail
from .backend import (
    BackendError,
    BackendMode,
    configure_backend_args,
    configure_sandbox_args,
    create_backend,
)

SESSION_INVALID_MARKERS = (
    "session not found",
    "session expired",
    "invalid session",
    "cannot resume session",
    "failed to resume session",
    "unknown session",
)
SESSION_RESET_MARKERS = ("loop detection halted the run",)
TRANSIENT_SERVICE_MARKERS = (
    "connection",
    "rate limit",
    "too many requests",
    "service unavailable",
    "temporarily unavailable",
    "try again later",
    "overloaded",
    "server overloaded",
    "upstream unavailable",
    "upstream connect error",
    "bad gateway",
    "gateway timeout",
    "http 429",
    "http 502",
    "http 503",
    "http 504",
)
DETERMINISTIC_SERVICE_MARKERS = (
    "dockerdesktoplinuxengine",
    "failed to connect to the docker api",
    "failed to obtain sandbox image",
    "sandbox image",
    "failed to relaunch the cli process",
)


class AIError(RunnerError):
    def __init__(
        self,
        message: str,
        *,
        transient: bool = False,
        recovery_key: str = "",
    ) -> None:
        super().__init__(message)
        self.transient = transient
        self.recovery_key = recovery_key


class AIClientProtocol(Protocol):
    session_id: str
    root: Path
    extra_args: Sequence[str]

    def ask(
        self,
        prompt: str,
        idle_timeout_after_change: float = 0,
        change_detected: Callable[[], bool] | None = None,
        timeout: int | None = None,
    ) -> str: ...

    def set_extra_args(self, extra_args: Sequence[str]) -> None: ...

    def set_runtime(
        self,
        mode: BackendMode,
        *,
        allow_project_read: bool = False,
        sandbox: bool = False,
    ) -> None: ...

    def context_snapshot(self, session_id: str) -> str: ...
    def context_usage_percent(self, snapshot: str) -> float | None: ...
    def compress_session(self, session_id: str) -> str: ...


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


def prepare_session_recovery(
    client,
    error: BackendError,
    message: str,
) -> None:
    diagnostics = error.diagnostics
    if not (
        diagnostics.get("loop_type")
        or should_reset_session(message)
    ):
        return
    try:
        from ..bootstrap import current_runtime

        current_runtime().hooks.model_error(client, error)
    except RuntimeError:
        pass
    diagnostics["session_recovery_action"] = (
        "compress_and_retry"
        if diagnostics.get("context_compress_status") == "done"
        else "stage_executor_retry"
    )


def _error_result(backend, error: BackendError) -> str:
    if not error.output:
        return ""
    try:
        return backend.decode(error.output).text
    except Exception:
        return error.output[-20_000:]


class AIClient:
    def __init__(
        self,
        backend: str,
        command: str | None,
        root: Path,
        extra_args: Sequence[str],
        session_id: str = "",
        timeout: int = DEFAULT_AGENT_TIMEOUT,
        debug_dir: Path | None = None,
    ) -> None:
        try:
            self._backend = create_backend(
                backend,
                command,
                root,
                extra_args,
                timeout,
            )
        except BackendError as error:
            raise AIError(
                str(error),
                transient=is_transient_service_error(str(error)),
            ) from error

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

    def set_extra_args(self, extra_args: Sequence[str]) -> None:
        values = list(extra_args)
        self.extra_args = values
        self._backend.extra_args = values

    def set_runtime(
        self,
        mode: str,
        *,
        allow_project_read: bool = False,
        sandbox: bool = False,
    ) -> None:
        self._backend.configure_runtime(
            mode,
            allow_project_read=allow_project_read,
            sandbox=sandbox,
        )

    def _publish_ai_event(
        self,
        kind: str,
        session_id: str,
        text: str,
        call_id: str = "",
        error: str = "",
        **metadata,
    ) -> str:
        from datetime import datetime, timezone

        value = call_id or datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S.%fZ"
        )
        try:
            from ..bootstrap import current_runtime

            current_runtime().events.publish({
                "type": kind,
                "debug_dir": str(self.debug_dir) if self.debug_dir else "",
                "call_id": value,
                "backend": self.backend,
                "cwd": str(self.root),
                "session": session_id,
                "text": text,
                "error": error,
                **metadata,
            })
        except RuntimeError:
            pass
        return value

    def _publish_ai_result(
        self,
        session_id: str,
        result: str,
        call_id: str,
        error: str = "",
        **metadata,
    ) -> None:
        self._publish_ai_event(
            "model.result",
            session_id,
            result,
            call_id,
            error,
            **metadata,
        )

    def _raise_backend_error(
        self,
        error: BackendError,
        call_session_id: str,
        debug_call_id: str,
    ) -> NoReturn:
        if error.session_id and not self.session_id:
            self.session_id = error.session_id

        message = str(error)
        expired_session = ""
        if self.session_id and is_session_invalid_error(message):
            expired_session = self.session_id
            self.session_id = ""
            error.diagnostics["session_recovery_action"] = "reset_session"
        else:
            prepare_session_recovery(self, error, message)

        actual_session_id = (
            error.session_id
            or self.session_id
            or call_session_id
        )
        self._publish_ai_result(
            actual_session_id,
            _error_result(self._backend, error),
            debug_call_id,
            diagnostic_detail(error),
            session_mode="resume" if call_session_id else "new",
            previous_session=call_session_id,
        )
        if expired_session:
            raise AIError(
                f"session {expired_session} is unavailable; "
                "a new session will continue from runner state"
            ) from error
        raise AIError(
            message,
            transient=is_transient_service_error(message),
            recovery_key=error.recovery_key,
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
        session_mode = "resume" if call_session_id else "new"
        debug_call_id = self._publish_ai_event(
            "model.prompt",
            call_session_id,
            prompt,
            session_mode=session_mode,
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
                call_session_id,
                debug_call_id,
            )
        finally:
            self.timeout = previous_timeout
            self._backend.timeout = previous_backend_timeout

        if result.session_id and not self.session_id:
            self.session_id = result.session_id
        actual_session_id = (
            self.session_id
            or result.session_id
            or call_session_id
        )
        self._publish_ai_result(
            actual_session_id,
            result.text,
            debug_call_id,
            session_mode=session_mode,
            previous_session=call_session_id,
        )
        return result.text

    def prepare_project(self) -> list[Path]:
        paths = self._backend.prepare_project()
        try:
            from ..bootstrap import register_resources

            register_resources(paths)
        except RuntimeError:
            pass
        return paths

    def update_goal_reference(self, goal_file: str | None) -> None:
        self._backend.update_goal_reference(goal_file)

    def context_snapshot(self, session_id: str) -> str:
        return self._backend.context_snapshot(session_id)

    def context_usage_percent(self, snapshot: str) -> float | None:
        return self._backend.context_usage_percent(snapshot)

    def compress_session(self, session_id: str) -> str:
        return self._backend.compress_session(session_id)


def build_backend_args(
    config,
    mode,
    *,
    allow_project_read: bool = False,
) -> list[str]:
    return configure_backend_args(
        config.backend,
        mode,
        config.agent_args,
        allow_project_read=allow_project_read,
        sandbox=getattr(config, "sandbox", False),
    )


def create_ai_client(
    config,
    root,
    debug_dir=None,
    *,
    mode="runtime",
    session_id="",
    timeout=None,
    allow_project_read=False,
    extra_args=None,
    constructor=AIClient,
):
    args = (
        configure_sandbox_args(
            config.backend,
            extra_args,
            sandbox=getattr(config, "sandbox", False),
        )
        if extra_args is not None
        else build_backend_args(
            config,
            mode,
            allow_project_read=allow_project_read,
        )
    )
    client = constructor(
        backend=config.backend,
        command=config.command,
        root=root,
        extra_args=args,
        session_id=session_id,
        timeout=(
            getattr(config, "agent_timeout", DEFAULT_AGENT_TIMEOUT)
            if timeout is None
            else timeout
        ),
        debug_dir=debug_dir,
    )
    if hasattr(client, "set_runtime"):
        client.set_runtime(
            mode,
            allow_project_read=allow_project_read,
            sandbox=getattr(config, "sandbox", False),
        )
    return client


def configure_ai_client(
    client,
    config,
    mode,
    *,
    allow_project_read=False,
) -> None:
    client.set_extra_args(
        build_backend_args(
            config,
            mode,
            allow_project_read=allow_project_read,
        )
    )
    if hasattr(client, "set_runtime"):
        client.set_runtime(
            mode,
            allow_project_read=allow_project_read,
            sandbox=getattr(config, "sandbox", False),
        )


__all__ = [
    "AIClient",
    "AIClientProtocol",
    "AIError",
    "DETERMINISTIC_SERVICE_MARKERS",
    "SESSION_INVALID_MARKERS",
    "SESSION_RESET_MARKERS",
    "TRANSIENT_SERVICE_MARKERS",
    "build_backend_args",
    "configure_ai_client",
    "create_ai_client",
    "is_session_invalid_error",
    "is_transient_service_error",
    "prepare_session_recovery",
    "should_reset_session",
]
