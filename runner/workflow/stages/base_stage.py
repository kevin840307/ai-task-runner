"""Generic AI-backed Stage. Retry routing and UI lifecycle live outside it."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from ...ai.client import configure_ai_client, create_ai_client
from ...ai.structured_output import structured_call
from ...errors import ConfigurationError
from ...prompts.context import build_stage_prompt_context
from ...prompts.loader import render_prompt
from ...prompts.protocols import append_stage_protocol
from .contracts import MODE_READONLY, StageContext, StageMode, StageResult

ResultParser = Callable[[str, StageContext], Any]
@dataclass(frozen=True)
class BaseStageSpec:
    name: str
    status: str = "AI Stage"
    prompt: str = ""
    instructions: str = ""
    detail: str = ""
    run_state: str = ""
    mode: StageMode = MODE_READONLY
    actor: str = "ai"
    allow_project_read: bool = False
    parser: ResultParser | None = None
    structured_retries: int = 1
    structured_fresh_retries: int = 0
    retry: int | None = None
    runs: int | None = None
    required_passes: int | None = None
    readonly_safety: str = ""
    track_changes: bool = False
    tolerate_restored_changes: bool = False
    timeout: float | None = None
    session_key: str = ""
    fresh_session_each_run: bool = False
    fresh_session_on_start: bool = False
    skip_on_error: bool = False
    produces: str = ""



class BaseStage:
    """Perform one or more AI interactions and return only resulting facts."""

    result_kind = "generic"
    parser_name = ""
    backend_mode = "runtime"
    timeout_config_attr = "agent_timeout"
    retry_config_attr = ""
    runs_config_attr = ""
    required_passes_config_attr = ""
    client_cache_key = ""
    result_flag = ""

    def __init__(self, spec: BaseStageSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.status = spec.status
        self.detail = spec.detail
        self.run_state = spec.run_state
        self.mode = spec.mode
        self.actor = spec.actor
        self.retry = spec.retry
        self.skip_on_error = spec.skip_on_error
        self.tolerate_restored_changes = spec.tolerate_restored_changes
        self.readonly_safety = spec.readonly_safety
        self.track_changes = spec.track_changes
        self.fresh_session_on_start = spec.fresh_session_on_start
        if spec.parser is None and self.parser_name:
            from ..result_parsers import PARSERS
            self.spec = replace(spec, parser=PARSERS[self.parser_name])
        self._completed_runs: list[StageResult] = []
        self._run_pending = False
        self._attempt_checkpoint = 0

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        """Perform one Stage attempt. Retry/Hook/Event are owned by StageExecutor."""
        if not self.enabled(ctx):
            return StageResult(self.name, "pass", output="STAGE_SKIPPED", skipped=True)

        runs = self._configured_int(ctx, self.spec.runs, self.runs_config_attr, 1)
        required = self._configured_int(
            ctx, self.spec.required_passes, self.required_passes_config_attr, 0
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
        self._completed_runs.clear()
        self._run_pending = False
        return result

    def enabled(self, ctx: StageContext) -> bool:
        return True

    def result_status(self, data: Any) -> Literal["pass", "fail"]:
        if not self.result_flag:
            return "pass"
        return "pass" if data[self.result_flag] is True else "fail"

    def retry_limit(self, ctx: StageContext) -> int | None:
        if self.spec.retry is not None:
            return self.spec.retry
        if self.retry_config_attr:
            return int(getattr(ctx.config, self.retry_config_attr))
        return None

    def discard_attempt_results(self) -> None:
        """Discard votes produced by an attempt rejected by execution hooks."""
        del self._completed_runs[self._attempt_checkpoint :]
        self._run_pending = False

    def _run_once(self, ctx: StageContext, previous: StageResult | None, client) -> StageResult:
        spec = self.spec
        backend_mode = self._backend_mode(ctx)
        configure_ai_client(
            client,
            ctx.config,
            backend_mode,
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
                    fresh_ask=lambda: self._structured_fresh_ask(ctx, client, previous),
                    fresh_retries=spec.structured_fresh_retries,
                )
                return "", data

            output, data = client.run_with_retry(
                call,
                spec.status,
                ctx.execution.label or spec.detail,
                ctx.config.api_retry_wait,
                ctx.config.api_retry_max_wait,
                max_elapsed=ctx.config.api_retry_timeout,
            )
            self._remember_prompt(ctx, client)
            status = self.result_status(data)
        finally:
            if client is ctx.ai_client:
                configure_ai_client(client, ctx.config, "runtime")

        return StageResult(self.name, status, output=output, data=data)

    @staticmethod
    def _configured_int(
        ctx: StageContext, explicit: int | None, field: str, default: int
    ) -> int:
        if explicit is not None:
            return int(explicit)
        return int(getattr(ctx.config, field)) if field else int(default)

    def _structured_fresh_ask(self, ctx: StageContext, client, previous: StageResult | None) -> str:
        client.session_id = ""
        original = self._original_prompt(ctx, previous)
        original_mode = ctx.execution.retry_mode
        try:
            ctx.execution.retry_mode = "recover"
            control = self._shared_control_prompt(ctx, previous, client)
        finally:
            ctx.execution.retry_mode = original_mode
        prompt = original.rstrip() + ("\n\n" + control if control else "")
        return self._ask(ctx, client, self._with_immutable_protocol(prompt))

    def _ask(self, ctx: StageContext, client, prompt: str) -> str:
        return client.ask(
            prompt,
            idle_timeout_after_change=ctx.config.agent_idle_after_change_timeout,
            change_detected=ctx.execution.change_detected,
            timeout=self._timeout(ctx),
        )

    def reset_session(self, ctx: StageContext) -> str:
        """Drop only this Stage's AI session so unrelated sessions remain reusable."""
        client = self._client(ctx)
        previous = str(getattr(client, "session_id", "") or "")
        client.session_id = ""
        if client is ctx.ai_client:
            ctx.state.ai_session_id = ""
        contracts = ctx.scratch.get("prompt_contracts")
        if isinstance(contracts, set) and previous:
            ctx.scratch["prompt_contracts"] = {
                item for item in contracts if not (isinstance(item, tuple) and len(item) == 2 and item[1] == previous)
            }
        ctx.save_state()
        return previous

    def _timeout(self, ctx: StageContext) -> float:
        if self.spec.timeout is not None:
            return float(self.spec.timeout)
        return float(getattr(ctx.config, self.timeout_config_attr))

    def _backend_mode(self, ctx: StageContext) -> str:
        return self.backend_mode

    def _client(self, ctx: StageContext):
        key = self.spec.session_key or self.client_cache_key
        if not key:
            return ctx.ai_client
        client = ctx.scratch.get(key)
        if client is None:
            client = create_ai_client(
                ctx.config,
                ctx.root,
                ctx.work / "debug",
                mode=self._backend_mode(ctx),
                timeout=self._timeout(ctx),
            )
            ctx.scratch[key] = client
        return client

    def _prompt(self, ctx: StageContext, previous: StageResult | None, client) -> str:
        body = self._original_prompt(ctx, previous)
        control = self._shared_control_prompt(ctx, previous, client)
        if control:
            body = body.rstrip() + "\n\n" + control
        return self._with_immutable_protocol(body)

    def _shared_control_prompt(
        self,
        ctx: StageContext,
        previous: StageResult | None,
        client,
    ) -> str:
        """Return one Runner-owned execution envelope shared by every AI Stage.

        Stage templates define role-specific behavior. Retry/continue/repair/recover
        semantics live here so semantic Stage types do not need parallel prompt files.
        """
        retry_mode = str(ctx.execution.retry_mode or "initial")
        same_session = bool(getattr(client, "session_id", ""))
        prompt_seen = self._prompt_seen(ctx, client)
        feedback = self._control_feedback(ctx, previous)
        if retry_mode == "retry":
            mode = "retry"
        elif retry_mode == "recover":
            mode = "recover"
        elif feedback or prompt_seen:
            mode = "continue"
        else:
            mode = "initial"
        if mode == "initial":
            return ""

        lines = [
            "RUNNER_SHARED_STAGE_CONTROL",
            f"mode: {mode}",
            f"attempt: {ctx.execution.attempt}",
            f"same_session: {'true' if same_session else 'false'}",
            f"source_stage: {getattr(previous, 'stage', '') or self.name}",
        ]
        if mode == "continue":
            lines.append(
                "Continue this Stage from current session/project evidence. "
                "Do not restart discovery or repeat unchanged successful work."
            )
        elif mode == "retry":
            lines.append(
                "Retry only the failed part of this Stage. Preserve valid existing work "
                "and do not repeat the exact failed action without new evidence."
            )
        else:
            lines.append(
                "Recover this same Stage in the fresh/current session. Inspect current "
                "durable project state first and preserve valid existing work."
            )

        error = str(ctx.execution.previous_error or "").strip()
        if error:
            lines.append("previous_error: " + error[-2000:])
        if feedback:
            lines.append("feedback:\n" + feedback[-3000:])
        lines.append(
            "The original Stage prompt and immutable output protocol remain authoritative."
        )
        return "\n".join(lines)

    @staticmethod
    def _control_feedback(
        ctx: StageContext,
        previous: StageResult | None,
    ) -> str:
        parts: list[str] = []
        task = ctx.task
        review = getattr(task, "last_review", None) if task is not None else None
        if isinstance(review, dict) and review.get("completed") is False:
            reason = str(review.get("reason") or "").strip()
            missing = review.get("missing_items")
            if reason:
                parts.append("Review: " + reason)
            if missing:
                parts.append("Review missing_items: " + json.dumps(missing, ensure_ascii=False))
        validator = str(getattr(ctx.state, "validator_output", "") or "").strip()
        if validator:
            parts.append("Validator: " + validator[-2000:])
        if previous is not None and previous.status in {"fail", "error", "replan"}:
            detail = str(previous.error or previous.output or "").strip()
            if detail:
                parts.append(f"{previous.stage}: {detail[-2000:]}")
        return "\n".join(parts)

    def _prompt_seen(self, ctx: StageContext, client) -> bool:
        session = str(getattr(client, "session_id", "") or "")
        if not session:
            return False
        return (self.spec.prompt, session) in ctx.scratch.get("prompt_contracts", set())

    def _remember_prompt(self, ctx: StageContext, client) -> None:
        session = str(getattr(client, "session_id", "") or "")
        if session and self.spec.prompt:
            ctx.scratch.setdefault("prompt_contracts", set()).add((self.spec.prompt, session))

    def _original_prompt(self, ctx: StageContext, previous: StageResult | None) -> str:
        if not self.spec.prompt:
            raise ConfigurationError(f"Base stage {self.spec.name} requires prompt")
        values = build_stage_prompt_context(ctx, self.spec.name, previous)
        values["instructions"] = self.spec.instructions
        rendered = render_prompt(self.spec.prompt, values)
        return self._augment_rendered_prompt(ctx, rendered)

    def _augment_rendered_prompt(self, ctx: StageContext, prompt: str) -> str:
        """Allow semantic Stage types to guarantee run-level instructions are visible.

        Editable templates remain free to render their normal context. Runner-owned
        semantic requirements can be injected here before the immutable wire
        protocol is appended, so custom templates cannot accidentally drop them.
        """
        return prompt

    def _with_immutable_protocol(self, prompt: str) -> str:
        """Append Runner-owned wire contract after editable Stage instructions."""
        return append_stage_protocol(prompt, self.result_kind)


BaseStage.spec_class = BaseStageSpec

__all__ = ["BaseStage", "BaseStageSpec"]
