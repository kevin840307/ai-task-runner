"""Shared execution boundary for every Stage."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, replace
from pathlib import Path

from ...bootstrap import current_runtime
from ...config.defaults import DEFAULT_MAX_ATTEMPTS
from ...errors import ConfigurationError, RunnerError, is_transient_error
from ...project.files import changed_project_files, project_manifest
from ...runtime import progress
from .contracts import Stage, StageContext, StageExecution, StageResult


@dataclass(frozen=True)
class StageAction:
    stage: Stage
    context: StageContext

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
        return getattr(self.stage, "mode", "readonly")

    @property
    def actor(self) -> str:
        return getattr(self.stage, "actor", "stage")

    @property
    def track_changes(self) -> bool:
        return self.mode == "write" or bool(getattr(self.stage, "track_changes", False))


class StageExecutor:
    """Run every Stage with one shared retry/session/Hook/Event/watchdog policy."""

    def __init__(self, hooks=None) -> None:
        self.hooks = hooks or current_runtime().hooks

    def run(
        self, stage: Stage, ctx: StageContext, previous: StageResult | None = None
    ) -> StageResult:
        if bool(getattr(stage, "fresh_session_on_start", False)) and self._has_session(
            ctx
        ):
            self._fresh_session(ctx)
        configured_retry = getattr(stage, "retry", None)
        retry_attr = str(getattr(stage, "retry_attr", "") or "")
        if retry_attr:
            configured_retry = getattr(ctx.config, retry_attr)
        effective_retry = (
            ctx.config.same_session_retries
            if configured_retry is None
            else configured_retry
        )
        unlimited_retry = effective_retry == -1
        # Unlimited recovery still rotates sessions after the normal per-session budget.
        per_session_retry = (
            ctx.config.same_session_retries if unlimited_retry else effective_retry
        )
        if per_session_retry == -1:
            per_session_retry = DEFAULT_MAX_ATTEMPTS
        same_retry_limit = max(0, int(per_session_retry))
        attempt = 0
        retry_mode = "initial"
        previous_error = ""
        run_state = str(getattr(stage, "run_state", "") or "")
        if run_state:
            ctx.set_stage(run_state, "")
        progress.stage_started(StageAction(stage, ctx))

        while True:
            attempt += 1
            ctx.execution = StageExecution(
                attempt=attempt,
                retry_mode=retry_mode,
                previous_error=previous_error,
            )
            result = self._attempt(stage, ctx, previous)

            if result.status != "error":
                self._reset_failure(ctx)
                break

            error = result.error or RunnerError(result.output or "stage error")
            error_retry_limit = max(
                0,
                int(getattr(error, "same_session_retry_limit", same_retry_limit)),
            )
            if is_transient_error(error):
                progress.service_wait_exhausted(stage.name, str(error)[-1000:])
                raise error

            if result.changed_files:
                self._reset_failure(ctx)
                break

            previous_error = str(error)

            if (
                bool(getattr(stage, "skip_on_error", False))
                and not unlimited_retry
                and error_retry_limit > 0
            ):
                if attempt <= error_retry_limit:
                    retry_mode = "same" if self._has_session(ctx) else "fresh"
                    self._sleep(ctx)
                    continue
                self._reset_failure(ctx)
                result = replace(result, status="pass", skipped=True)
                break

            failure_count, fresh_round = self._record_failure(stage, ctx, error)
            if failure_count <= error_retry_limit:
                retry_mode = "same" if self._has_session(ctx) else "fresh"
                self._sleep(ctx)
                continue

            if fresh_round == 0:
                self._fresh_session(ctx)
                ctx.state.fresh_session_round = 1
                ctx.save_state()
                retry_mode = "fresh"
                continue

            if unlimited_retry:
                self._reset_failure(ctx)
                self._fresh_session(ctx)
                ctx.save_state()
                retry_mode = "fresh"
                self._sleep(ctx)
                continue

            result = replace(result, status="replan")
            break

        try:
            result = stage.finish(ctx, result)
        except ConfigurationError:
            raise
        except BaseException as error:
            result = StageResult.error_result(stage.name, error)

        ctx.execution = StageExecution()
        ctx.save_state()
        progress.stage_finished(StageAction(stage, ctx), result)
        return result

    def _attempt(
        self, stage: Stage, ctx: StageContext, previous: StageResult | None
    ) -> StageResult:
        action = StageAction(stage, ctx)
        before = project_manifest(ctx.root, ctx.work) if action.track_changes else None
        tokens = []
        try:
            tokens = self.hooks.before(action)
            change_detected = self.hooks.change_detector(action, tokens, lambda: False)
            ctx.execution.change_detected = change_detected
            result = stage.run(ctx, previous)
            if not isinstance(result, StageResult):
                raise RunnerError(f"stage {stage.name} must return StageResult")
            if result.stage != stage.name:
                result = replace(result, stage=stage.name)
        except BaseException as error:
            result = StageResult.error_result(stage.name, error)

        if before is not None:
            changed = changed_project_files(ctx.root, ctx.work, before)
            if changed:
                result = replace(
                    result,
                    changed_files=list(
                        dict.fromkeys([*result.changed_files, *changed])
                    ),
                )

        hooks_failed = False
        try:
            violations = self.hooks.after(action, tokens)
        except BaseException as error:
            violations = []
            hooks_failed = True
            if result.status != "error":
                result = StageResult.error_result(stage.name, error)

        if violations:
            tolerate = bool(getattr(stage, "tolerate_restored_changes", False))
            violations = [
                violation
                for violation in violations
                if not (tolerate and getattr(violation, "kind", "") == "readonly")
            ]
        if hooks_failed or violations:
            discard = getattr(stage, "discard_attempt_results", None)
            if callable(discard):
                discard()
        if violations:
            if result.status == "error":
                result = replace(result, changed_files=[])
            else:
                messages = [violation.message for violation in violations]
                result = StageResult.error_result(
                    stage.name, RunnerError("; ".join(messages))
                )
        return result

    @staticmethod
    def _failure_key(
        stage: Stage, ctx: StageContext, error: BaseException
    ) -> tuple[str, str]:
        task_id = ctx.task.id if ctx.task is not None else "-"
        scope = f"{stage.name}:{task_id}"
        text = "\n".join(
            line.strip() for line in str(error).splitlines() if line.strip()
        )
        normalized = text[-2000:] or type(error).__name__
        return scope, hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _record_failure(
        self, stage: Stage, ctx: StageContext, error: BaseException
    ) -> tuple[int, int]:
        scope, key = self._failure_key(stage, ctx, error)
        state = ctx.state
        if state.failure_scope != scope or state.failure_key != key:
            state.failure_scope = scope
            state.failure_key = key
            state.same_failures = 1
            state.fresh_session_round = 0
        else:
            state.same_failures += 1
        ctx.set_stage(getattr(state, "stage", stage.name), str(error))
        return state.same_failures, state.fresh_session_round

    @staticmethod
    def _reset_failure(ctx: StageContext) -> None:
        state = ctx.state
        state.failure_scope = ""
        state.failure_key = ""
        state.same_failures = 0
        state.fresh_session_round = 0

    @staticmethod
    def _fresh_session(ctx: StageContext) -> None:
        previous = ctx.ai_client.session_id
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
            time.sleep(ctx.config.stage_retry_delay)


__all__ = ["StageAction", "StageExecutor"]
