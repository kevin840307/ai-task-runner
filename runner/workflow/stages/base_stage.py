"""Generic AI-backed Stage. Retry routing and UI lifecycle live outside it."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from ...ai.client import configure_ai_client, create_ai_client
from ...ai.structured_output import structured_call
from ...errors import ConfigurationError
from ...prompts.context import build_stage_prompt_context
from ...prompts.loader import render_prompt, structured_retry_prompt
from .contracts import StageContext, StageResult

ResultParser = Callable[[str, StageContext], Any]
StatusResolver = Callable[[Any], Literal["pass", "fail"]]
Condition = Callable[[StageContext], bool]
ResultHandler = Callable[[StageContext, StageResult], StageResult]


@dataclass(frozen=True)
class BaseStageSpec:
    name: str
    status: str
    prompt: str = ""
    instructions: str = ""
    detail: str = ""
    run_state: str = ""
    mode: Literal["readonly", "write"] = "readonly"
    actor: str = "ai"
    backend_mode: str = "runtime"
    allow_project_read: bool = False
    parser: ResultParser | None = None
    result_status: StatusResolver | None = None
    condition: Condition | None = None
    structured_retries: int = 1
    structured_fresh_retries: int = 0
    retry: int | None = None
    retry_attr: str = ""
    runs: int = 1
    runs_field: str = ""
    required_passes: int = 0
    required_passes_field: str = ""
    track_changes: bool = False
    tolerate_restored_changes: bool = False
    timeout_attr: str = "agent_timeout"
    client_cache_key: str = ""
    fresh_session_each_run: bool = False
    fresh_session_on_start: bool = False
    skip_on_error: bool = False
    result_handler: ResultHandler | None = None
    plan_only_stop: bool = False


class BaseStage:
    """Perform one or more AI interactions and return only resulting facts."""

    def __init__(self, spec: BaseStageSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.status = spec.status
        self.detail = spec.detail
        self.run_state = spec.run_state
        self.mode = spec.mode
        self.actor = spec.actor
        self.skip_on_error = spec.skip_on_error
        self.tolerate_restored_changes = spec.tolerate_restored_changes
        self.retry = spec.retry
        self.retry_attr = spec.retry_attr
        self.plan_only_stop = spec.plan_only_stop
        self.fresh_session_on_start = spec.fresh_session_on_start
        self._completed_runs: list[StageResult] = []
        self._run_pending = False
        self._attempt_checkpoint = 0

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        """Perform one Stage attempt. Retry/Hook/Event are owned by StageExecutor."""
        if self.spec.condition is not None and not self.spec.condition(ctx):
            return StageResult(self.name, "pass", output="STAGE_SKIPPED", skipped=True)

        runs = self._configured_int(ctx, self.spec.runs_field, self.spec.runs)
        required = self._configured_int(
            ctx,
            self.spec.required_passes_field,
            self.spec.required_passes,
        ) or (runs // 2 + 1)
        if runs < 1 or not 1 <= required <= runs:
            raise ConfigurationError(
                f"Base stage {self.name} requires 1 <= required_passes <= runs"
            )

        self._attempt_checkpoint = len(self._completed_runs)
        while len(self._completed_runs) < runs:
            client = self._client(ctx)
            if self.spec.fresh_session_each_run and not self._run_pending:
                client.session_id = ""
            self._run_pending = True
            self._completed_runs.append(self._run_once(ctx, previous, client))
            self._run_pending = False

        results = list(self._completed_runs)

        if runs == 1:
            return results[0]

        passed = sum(item.status == "pass" for item in results)
        status = "pass" if passed >= required else "fail"
        return StageResult(
            self.name,
            status,
            output=json.dumps(
                {
                    "passed": status == "pass",
                    "passes": passed,
                    "required_passes": required,
                    "runs": [item.data for item in results],
                },
                ensure_ascii=False,
            ),
            data=[item.data for item in results],
        )

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        try:
            if self.spec.result_handler is None:
                return result
            return self.spec.result_handler(ctx, result)
        finally:
            self._completed_runs.clear()
            self._run_pending = False

    def discard_attempt_results(self) -> None:
        """Discard votes produced by an attempt rejected by execution hooks."""
        del self._completed_runs[self._attempt_checkpoint :]
        self._run_pending = False

    def _run_once(self, ctx: StageContext, previous: StageResult | None, client) -> StageResult:
        spec = self.spec
        configure_ai_client(
            client,
            ctx.config,
            spec.backend_mode,
            allow_project_read=spec.allow_project_read,
        )
        try:
            prompt = self._prompt(ctx, previous, client)

            def call() -> tuple[str, Any]:
                if spec.parser is None:
                    raw = self._ask(ctx, client, prompt)
                    return raw, raw
                data = structured_call(
                    prompt,
                    lambda text: spec.parser(text, ctx),
                    lambda text: self._ask(ctx, client, text),
                    retries=spec.structured_retries,
                    retry_prompt=structured_retry_prompt,
                    fresh_ask=lambda: self._structured_fresh_ask(ctx, client, previous),
                    fresh_retries=spec.structured_fresh_retries,
                )
                return "", data

            output, data = client.run_with_retry(
                call,
                spec.status,
                spec.detail,
                ctx.config.api_retry_wait,
                ctx.config.api_retry_max_wait,
                max_elapsed=ctx.config.api_retry_timeout,
            )
            status = spec.result_status(data) if spec.result_status else "pass"
        finally:
            if client is ctx.ai_client:
                configure_ai_client(client, ctx.config, "runtime")

        return StageResult(self.name, status, output=output, data=data)

    @staticmethod
    def _configured_int(ctx: StageContext, field: str, default: int) -> int:
        return int(getattr(ctx.config, field)) if field else int(default)

    def _structured_fresh_ask(self, ctx: StageContext, client, previous: StageResult | None) -> str:
        client.session_id = ""
        original = self._original_prompt(ctx, previous)
        return self._ask(ctx, client, self._fresh_session_prompt(original))

    def _ask(self, ctx: StageContext, client, prompt: str) -> str:
        return client.ask(
            prompt,
            idle_timeout_after_change=ctx.config.agent_idle_after_change_timeout,
            change_detected=ctx.execution.change_detected,
            timeout=getattr(ctx.config, self.spec.timeout_attr),
        )

    def _client(self, ctx: StageContext):
        key = self.spec.client_cache_key
        if not key:
            return ctx.ai_client
        client = ctx.scratch.get(key)
        if client is None:
            client = create_ai_client(
                ctx.config,
                ctx.root,
                ctx.work / "debug",
                mode=self.spec.backend_mode,
                timeout=getattr(ctx.config, self.spec.timeout_attr),
            )
            ctx.scratch[key] = client
        return client

    def _prompt(self, ctx: StageContext, previous: StageResult | None, client) -> str:
        original = self._original_prompt(ctx, previous)
        mode = ctx.execution.retry_mode
        if mode == "initial":
            return original
        if mode == "same" and getattr(client, "session_id", ""):
            return self._same_session_prompt(ctx)
        return self._fresh_session_prompt(original)

    def _original_prompt(self, ctx: StageContext, previous: StageResult | None) -> str:
        if not self.spec.prompt:
            raise ConfigurationError(f"Base stage {self.spec.name} requires prompt")
        values = build_stage_prompt_context(ctx, self.spec.name, previous)
        values["instructions"] = self.spec.instructions
        return render_prompt(self.spec.prompt, values)

    def _same_session_prompt(self, ctx: StageContext) -> str:
        error = ctx.execution.previous_error.strip()
        readonly = (
            " Do not modify project files; the previous attempt was restored if it changed them."
            if self.spec.mode == "readonly"
            else ""
        )
        loop_note = (
            " Do not repeat the exact failed action; use a different approach."
            if "loop" in error.lower()
            else ""
        )
        return (
            f"Continue the same {self.name} stage. Fix only the previous failure and preserve valid existing work."
            f"{readonly}{loop_note}\n"
            + (f"Previous failure: {error[-2000:]}\n" if error else "")
            + "Return the result required by the original stage instructions; do not restart unrelated work.\n"
        )

    def _fresh_session_prompt(self, original: str) -> str:
        return (
            f"Continue the same {self.name} stage in a fresh session. "
            "Inspect the CURRENT project state first and preserve valid existing work.\n\n"
            f"Stage instructions:\n{original}"
        )



BaseStage.spec_class = BaseStageSpec

__all__ = ["BaseStage", "BaseStageSpec", "ResultHandler"]
