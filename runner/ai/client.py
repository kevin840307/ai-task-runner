"""Public AI client API and session/recovery coordination."""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn, TypeVar

from ..errors import RunnerError, diagnostic_detail
from ..runtime import events
from .diagnostics import error_result, prepare_session_recovery
from .errors import AIError, BackendError
from .session import is_session_invalid_error, is_transient_service_error

T = TypeVar("T")

class AIClient:
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
            from ..backends.registry import create_backend
            self._backend = create_backend(
                backend, command, root, extra_args, timeout
            )
        except BackendError as error:
            raise AIError(str(error), transient=is_transient_service_error(str(error))) from error

        # Preserve the simple public attributes from the original single-file AIClient.
        self.backend = self._backend.name
        self.base_command = self._backend.base_command
        self.root = self._backend.root
        self.extra_args = self._backend.extra_args
        self.session_id = session_id
        self.timeout = timeout
        self.debug_dir = debug_dir

    def run_with_retry(
        self,
        call,
        status: str,
        detail: str,
        initial_wait: float,
        max_wait: float,
        *,
        max_elapsed: float = 0,
    ):
        """Run one AI operation with transport-only reliability.

        Stage retry/session replacement is owned by StageExecutor; stages return final follow-up facts to Pipeline.
        """
        return _run_with_backoff(
            call, status, detail, initial_wait, max_wait, max_elapsed=max_elapsed
        )

    @property
    def name(self) -> str:
        return self.backend

    def set_extra_args(self, extra_args: Sequence[str]) -> None:
        """Switch stage capabilities without replacing this client or session."""
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
        """Update backend stage/sandbox policy without replacing the session."""
        self._backend.configure_runtime(
            mode,
            allow_project_read=allow_project_read,
            sandbox=sandbox,
        )

    def _publish_ai_event(
        self, kind: str, session_id: str, text: str, call_id: str = "", error: str = "", **metadata
    ) -> str:
        from datetime import datetime, timezone
        value = call_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
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
        self, session_id: str, result: str, call_id: str, error: str = "", **metadata
    ) -> None:
        self._publish_ai_event("model.result", session_id, result, call_id, error, **metadata)

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
        actual_session_id = error.session_id or self.session_id or call_session_id
        self._publish_ai_result(
            actual_session_id,
            error_result(self._backend, error),
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
            "model.prompt", call_session_id, prompt, session_mode=session_mode
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
        actual_session_id = self.session_id or result.session_id or call_session_id
        self._publish_ai_result(
            actual_session_id, result.text, debug_call_id,
            session_mode=session_mode, previous_session=call_session_id,
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




def build_backend_args(config, mode, *, allow_project_read=False):
    """Build backend arguments for one stage without a factory object."""
    from ..backends.registry import configure_backend_args
    return configure_backend_args(
        config.backend, mode, config.agent_args,
        allow_project_read=allow_project_read,
        sandbox=getattr(config, "sandbox", False),
    )


def create_ai_client(config, root, debug_dir=None, *, mode="runtime", session_id="", timeout=None, allow_project_read=False, extra_args=None, constructor=AIClient):
    """Create one AI client directly; no factory lifecycle is required."""
    from ..backends.registry import configure_sandbox_args
    from ..config.defaults import DEFAULT_AGENT_TIMEOUT
    args = (
        configure_sandbox_args(config.backend, extra_args, sandbox=getattr(config, "sandbox", False))
        if extra_args is not None
        else build_backend_args(config, mode, allow_project_read=allow_project_read)
    )
    client = constructor(
        backend=config.backend, command=config.command, root=root, extra_args=args,
        session_id=session_id,
        timeout=getattr(config, "agent_timeout", DEFAULT_AGENT_TIMEOUT) if timeout is None else timeout,
        debug_dir=debug_dir,
    )
    if hasattr(client, "set_runtime"):
        client.set_runtime(
            mode,
            allow_project_read=allow_project_read,
            sandbox=getattr(config, "sandbox", False),
        )
    return client


def configure_ai_client(client, config, mode, *, allow_project_read=False):
    """Switch stage capabilities on an existing live AI session."""
    client.set_extra_args(build_backend_args(config, mode, allow_project_read=allow_project_read))
    if hasattr(client, "set_runtime"):
        client.set_runtime(
            mode,
            allow_project_read=allow_project_read,
            sandbox=getattr(config, "sandbox", False),
        )




def _run_with_backoff(
    action: Callable[[], T],
    status: str,
    detail: str,
    wait: float,
    max_wait: float,
    *,
    max_elapsed: float = 0,
) -> T:
    """Retry only transient API/service failures; StageExecutor owns every real failure."""
    delay = max(0.0, wait)
    started = time.monotonic()
    retrying = False
    while True:
        if retrying:
            events.start(status, detail)
        try:
            return action()
        except RunnerError as error:
            if not bool(getattr(error, "transient", False)):
                raise
            elapsed = time.monotonic() - started
            if max_elapsed > 0 and elapsed >= max_elapsed:
                raise
            events.stop("API/服務異常，等待後重試", diagnostic_detail(error))
            retrying = True
            if delay:
                sleep_for = min(delay, max_elapsed - elapsed) if max_elapsed > 0 else delay
                if sleep_for > 0:
                    time.sleep(sleep_for)
                delay = min(max_wait, max(wait, delay * 2))



__all__ = ["AIClient", "build_backend_args", "configure_ai_client", "create_ai_client"]
