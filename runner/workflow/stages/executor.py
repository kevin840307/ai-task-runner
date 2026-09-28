"""Reliable execution boundary shared by every Stage."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ...bootstrap import current_runtime
from ...config.defaults import DEFAULT_PER_SESSION_ATTEMPTS
from ...errors import ConfigurationError, RunnerError, is_transient_error
from ...project.files import changed_project_files, project_manifest
from ...runtime import progress
from ...runtime.heartbeat import sleep_with_heartbeat
from .contracts import (
    MODE_READONLY,
    MODE_WRITE,
    Stage,
    StageContext,
    StageExecution,
    StageResult,
)


@dataclass(frozen=True)
class StageAction:
    stage: Stage
    context: StageContext
    label: str = ""

    @property
    def name(self) -> str:
        return self.stage.name

    @property
    def root(self) -> Path:
        return self.context.root.resolve()

    @property
    def work(self) -> Path:
        return self.context.work.resolve()

    @property
    def mode(self) -> str:
        return getattr(self.stage, "mode", MODE_READONLY)

    @property
    def actor(self) -> str:
        return getattr(self.stage, "actor", "stage")

    @property
    def track_changes(self) -> bool:
        return self.mode == MODE_WRITE or bool(getattr(self.stage, "track_changes", False))


class StageExecutor:
    """Run a Stage until it returns a semantic result or an unrecoverable error.

    The unattended default is unlimited technical recovery. One session stays
    bounded: after a small same-session retry budget, the Stage receives a fresh
    session and continues. Retry counters are attempt-local; durable resume only
    needs to know which Workflow Stage is current.
    """

    def __init__(self, hooks=None) -> None:
        self.hooks = hooks or current_runtime().hooks

    def run(
        self,
        stage: Stage,
        ctx: StageContext,
        previous: StageResult | None = None,
        *,
        label: str = "",
    ) -> StageResult:
        if bool(getattr(stage, "fresh_session_on_start", False)) and self._has_session(ctx):
            self._fresh_session(stage, ctx)

        configured = self._retry_limit(stage, ctx)
        unlimited = configured == -1
        same_session_limit = (
            DEFAULT_PER_SESSION_ATTEMPTS if unlimited else max(0, configured)
        )
        same_session_failures = 0
        fresh_used = False
        attempt = 0
        retry_mode = "initial"
        previous_error = ""

        run_state = str(getattr(stage, "run_state", "") or "")
        if run_state:
            ctx.set_stage(run_state, "")
        progress.stage_started(StageAction(stage, ctx, label))

        while True:
            attempt += 1
            ctx.execution = StageExecution(
                attempt=attempt,
                retry_mode=retry_mode,
                previous_error=previous_error,
                label=label,
            )
            result = self._attempt(stage, ctx, previous)
            if result.status != "error":
                break

            error = result.error or RunnerError(result.output or "stage error")
            if isinstance(error, ConfigurationError):
                raise error
            if is_transient_error(error):
                progress.service_wait_exhausted(stage.name, str(error)[-1000:])
                raise error
            if result.changed_files:
                break

            previous_error = str(error)
            limit = max(
                0,
                int(getattr(error, "same_session_retry_limit", same_session_limit)),
            )
            if same_session_failures < limit:
                same_session_failures += 1
                retry_mode = "retry" if self._has_session(ctx) else "recover"
                self._sleep(ctx)
                continue

            if unlimited or not fresh_used:
                self._fresh_session(stage, ctx)
                same_session_failures = 0
                fresh_used = True
                retry_mode = "recover"
                self._sleep(ctx)
                continue

            break

        try:
            result = stage.finish(ctx, result)
            from ..reducers import reduce_result

            produces = str(getattr(getattr(stage, "spec", None), "produces", "") or "")
            kind = produces or str(getattr(stage, "result_kind", "generic") or "generic")
            if result.kind != kind:
                result = replace(result, kind=kind)
            result = reduce_result(ctx, result)
        except ConfigurationError:
            raise
        except Exception as error:
            result = StageResult.error_result(stage.name, error)

        ctx.execution = StageExecution()
        ctx.save_state()
        progress.stage_finished(StageAction(stage, ctx, label), result)
        return result

    def _attempt(
        self,
        stage: Stage,
        ctx: StageContext,
        previous: StageResult | None,
    ) -> StageResult:
        action = StageAction(stage, ctx)
        before = project_manifest(ctx.root, ctx.work) if action.track_changes else None
        tokens = []
        try:
            tokens = self.hooks.before(action)
            ctx.execution.change_detected = self.hooks.change_detector(
                action, tokens, lambda: False
            )
            result = stage.run(ctx, previous)
            if not isinstance(result, StageResult):
                raise RunnerError(f"stage {stage.name} must return StageResult")
            if result.stage != stage.name:
                result = replace(result, stage=stage.name)
        except (KeyboardInterrupt, SystemExit):
            try:
                self.hooks.after(action, tokens)
            except BaseException:
                pass
            raise
        except Exception as error:
            result = StageResult.error_result(stage.name, error)

        if before is not None:
            changed = changed_project_files(ctx.root, ctx.work, before)
            if changed:
                result = replace(
                    result,
                    changed_files=list(dict.fromkeys([*result.changed_files, *changed])),
                )

        try:
            violations = self.hooks.after(action, tokens)
        except Exception as error:
            violations = []
            if result.status != "error":
                result = StageResult.error_result(stage.name, error)

        if violations:
            tolerate = bool(getattr(stage, "tolerate_restored_changes", False))
            violations = [
                item
                for item in violations
                if not (tolerate and getattr(item, "kind", "") == MODE_READONLY)
            ]
        if violations:
            discard = getattr(stage, "discard_attempt_results", None)
            if callable(discard):
                discard()
            result = StageResult.error_result(
                stage.name,
                RunnerError("; ".join(item.message for item in violations)),
            )
        return result

    @staticmethod
    def _retry_limit(stage: Stage, ctx: StageContext) -> int:
        value = getattr(stage, "retry_limit", None)
        configured = value(ctx) if callable(value) else getattr(stage, "retry", None)
        if configured is None:
            configured = ctx.config.stage_retries
        return int(configured)

    def _fresh_session(self, stage: Stage, ctx: StageContext) -> None:
        reset = getattr(stage, "reset_session", None)
        if callable(reset):
            previous = str(reset(ctx) or "")
        else:
            previous = str(ctx.ai_client.session_id or "")
            ctx.reset_sessions()
        progress.session_fresh(previous)

    @staticmethod
    def _has_session(ctx: StageContext) -> bool:
        return bool(ctx.ai_client.session_id) or any(
            bool(getattr(value, "session_id", "")) for value in ctx.scratch.values()
        )

    @staticmethod
    def _sleep(ctx: StageContext) -> None:
        if ctx.config.stage_retry_delay:
            sleep_with_heartbeat(ctx.config.stage_retry_delay)


__all__ = ["StageAction", "StageExecutor"]
