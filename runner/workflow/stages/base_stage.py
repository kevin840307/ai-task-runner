"""Generic AI-backed Stage. Retry routing and UI lifecycle live outside it."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

from ...agent import AIClientProtocol, configure_ai_client, create_ai_client, structured_call
from ...config.runtime import RuntimeConfig
from ...errors import ConfigurationError, RunnerError
from ...prompting import append_stage_protocol, build_stage_prompt_context, render_prompt
from ...runtime.run_state import RunState, Task

StageStatus = Literal["pass", "fail", "error"]
StageMode = Literal["readonly", "write"]
StageResultKind = Literal["generic", "tasks", "stages", "task", "review", "validation", "handoff"]
AIStageProfile = Literal["generic", "execute", "review"]
SessionPolicy = Literal["auto", "main", "role", "fresh"]
MODE_READONLY: StageMode = "readonly"
MODE_WRITE: StageMode = "write"


@dataclass(frozen=True)
class StageResult:
    stage: str
    status: StageStatus
    output: str = ""
    error: RunnerError | None = None
    changed_files: list[str] = field(default_factory=list)
    data: object | None = None
    kind: StageResultKind = "generic"

    @classmethod
    def error_result(cls, stage: str, error: BaseException) -> "StageResult":
        runner_error = (
            error if isinstance(error, RunnerError) else RunnerError(str(error))
        )
        return cls(
            stage,
            "error",
            output=str(runner_error),
            error=runner_error,
        )


@dataclass
class StageExecution:
    change_detected: Callable[[], bool] | None = None
    attempt: int = 1
    retry_mode: Literal["initial", "retry", "recover"] = "initial"
    previous_error: str = ""
    label: str = ""


@dataclass
class StageContext:
    config: RuntimeConfig
    root: Path
    work: Path
    state: RunState
    ai_client: AIClientProtocol
    state_file: Path
    validator_path: Path | None
    validator_is_ai: bool
    save_state: Callable[[], None]
    set_stage: Callable[[str, str], None]
    scratch: dict[str, Any] = field(default_factory=dict)
    execution: StageExecution = field(default_factory=StageExecution)

    @property
    def task(self) -> Task | None:
        return (
            self.state.tasks[self.state.current]
            if self.state.current < len(self.state.tasks)
            else None
        )

    def require_task(self, stage: str) -> Task:
        task = self.task
        if task is None:
            raise RunnerError(f"{stage} stage requires a pending task")
        return task

    def save_session(self) -> None:
        self.state.ai_session_id = self.ai_client.session_id
        self.save_state()

    def reset_sessions(self) -> None:
        for value in (self.ai_client, *self.scratch.values()):
            if hasattr(value, "session_id"):
                value.session_id = ""
        self.state.ai_session_id = ""
        self.state.stage_sessions.clear()
        self.scratch.pop("prompt_contracts", None)
        self.save_state()


class Stage(Protocol):
    name: str
    mode: str
    actor: str
    status: str
    detail: str

    def run(
        self,
        ctx: StageContext,
        previous: StageResult | None = None,
    ) -> StageResult: ...

    def finish(
        self,
        ctx: StageContext,
        result: StageResult,
    ) -> StageResult: ...


ResultParser = Callable[[str, StageContext], Any]
@dataclass(frozen=True)
class BaseStageSpec:
    name: str
    profile: AIStageProfile = "generic"
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
    runs: int | None = None
    required_passes: int | None = None
    readonly_safety: str = ""
    track_changes: bool = False
    tolerate_restored_changes: bool = False
    timeout: float | None = None
    session_key: str = ""
    session_policy: SessionPolicy = "auto"
    fresh_session_each_run: bool = False
    fresh_session_on_start: bool = False
    produces: str = ""
    max_failures: int | None = None



class BaseStage:
    """Perform one or more AI interactions and return only resulting facts."""

    result_kind = "generic"
    parser_name = ""
    backend_mode = "runtime"
    timeout_config_attr = "agent_timeout"
    runs_config_attr = ""
    required_passes_config_attr = ""
    client_cache_key = ""
    result_flag = ""

    def __init__(self, spec: BaseStageSpec) -> None:
        profile = str(spec.profile or "generic")
        if profile not in {"generic", "execute", "review"}:
            raise ConfigurationError(
                f"AI Stage {spec.name} profile must be generic, execute, or review"
            )
        if profile == "execute":
            spec = replace(
                spec,
                status=spec.status if spec.status != "AI Stage" else "AI 正在處理目前任務",
                prompt=spec.prompt or "common/execution.md",
                run_state=spec.run_state or "executing",
                mode=MODE_WRITE,
                actor="executor" if spec.actor == "ai" else spec.actor,
                track_changes=True if not spec.track_changes else spec.track_changes,
            )
            self.result_kind = "task"
        elif profile == "review":
            from ..results import PARSERS
            spec = replace(
                spec,
                status=spec.status if spec.status != "AI Stage" else "AI 正在確認任務是否完成",
                prompt=spec.prompt or "common/review.md",
                run_state=spec.run_state or "reviewing",
                mode=MODE_READONLY,
                parser=spec.parser or PARSERS["review"],
            )
            self.result_kind = "review"
            self.backend_mode = "review"
            self.timeout_config_attr = "planning_timeout"
            self.client_cache_key = "review_client"
            self.result_flag = "completed"
        if spec.produces:
            self.result_kind = spec.produces
        self.spec = spec
        self.name = spec.name
        self.status = spec.status
        self.detail = spec.detail
        self.run_state = spec.run_state
        self.mode = spec.mode
        self.actor = spec.actor
        self.tolerate_restored_changes = spec.tolerate_restored_changes
        self.readonly_safety = spec.readonly_safety
        self.track_changes = spec.track_changes
        self.fresh_session_on_start = (
            spec.session_policy == "auto" and spec.fresh_session_on_start
        )
        if spec.parser is None and self.parser_name:
            from ..results import PARSERS
            self.spec = replace(spec, parser=PARSERS[self.parser_name])
        self._completed_runs: list[StageResult] = []
        self._run_pending = False
        self._attempt_checkpoint = 0

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        """Perform one Stage attempt. Retry/Hook/Event are owned by StageExecutor."""
        if not self.enabled(ctx):
            return StageResult(self.name, "pass", output="STAGE_DISABLED")

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
            if (
                self.spec.session_policy == "fresh"
                or (
                    self.spec.session_policy == "auto"
                    and self.spec.fresh_session_each_run
                )
            ) and not self._run_pending:
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

            output, data = call()
            self._remember_prompt(ctx, client)
            self._persist_session(ctx, client)
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
        prompt = "Stage instructions:\n" + original.rstrip()
        if control:
            prompt += "\n\n" + control
        return self._ask(ctx, client, self._with_immutable_protocol(prompt))

    def _ask(self, ctx: StageContext, client, prompt: str) -> str:
        return client.ask(
            prompt,
            idle_timeout_after_change=ctx.config.agent_idle_after_change_timeout,
            change_detected=ctx.execution.change_detected,
            timeout=self._timeout(ctx),
        )

    def has_session(self, ctx: StageContext) -> bool:
        return bool(getattr(self._client(ctx), "session_id", ""))

    def reset_session(self, ctx: StageContext) -> str:
        """Drop only this Stage's AI session so unrelated sessions remain reusable."""
        client = self._client(ctx)
        previous = str(getattr(client, "session_id", "") or "")
        client.session_id = ""
        if client is ctx.ai_client:
            ctx.state.ai_session_id = ""
        elif self.spec.session_policy == "role":
            ctx.state.stage_sessions.pop(self.name, None)
        contracts = ctx.scratch.get("prompt_contracts")
        if isinstance(contracts, dict) and previous:
            current = contracts.get(self.name)
            if (
                isinstance(current, tuple)
                and len(current) == 2
                and current[1] == previous
            ):
                contracts.pop(self.name, None)
        ctx.save_state()
        return previous

    def _timeout(self, ctx: StageContext) -> float:
        if self.spec.timeout is not None:
            return float(self.spec.timeout)
        return float(getattr(ctx.config, self.timeout_config_attr))

    def _backend_mode(self, ctx: StageContext) -> str:
        return self.backend_mode

    def _client(self, ctx: StageContext):
        policy = self.spec.session_policy
        if policy == "main":
            return ctx.ai_client

        if policy in {"role", "fresh"}:
            key = f"stage_session:{self.name}"
            client = ctx.scratch.get(key)
            if client is None:
                client = create_ai_client(
                    ctx.config,
                    ctx.root,
                    ctx.work / "debug",
                    mode=self._backend_mode(ctx),
                    timeout=self._timeout(ctx),
                    session_id=(
                        ctx.state.stage_sessions.get(self.name, "")
                        if policy == "role"
                        else ""
                    ),
                )
                ctx.scratch[key] = client
            return client

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

    def _persist_session(self, ctx: StageContext, client) -> None:
        session_id = str(getattr(client, "session_id", "") or "")
        if self.spec.session_policy == "role":
            if session_id:
                ctx.state.stage_sessions[self.name] = session_id
            else:
                ctx.state.stage_sessions.pop(self.name, None)
            ctx.save_state()
        elif client is ctx.ai_client and session_id:
            ctx.state.ai_session_id = session_id
            ctx.save_state()

    def _prompt(self, ctx: StageContext, previous: StageResult | None, client) -> str:
        original = self._original_prompt(ctx, previous)
        control = self._shared_control_prompt(ctx, previous, client)
        reuse_session_context = bool(
            control
            and ctx.execution.retry_mode != "recover"
            and getattr(client, "session_id", "")
            and self._prompt_seen(ctx, client)
        )
        if reuse_session_context:
            body = control
        else:
            body = original
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

        Stage templates define role-specific behavior. Retry/continue/recover
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
            f"stage: {self.name}",
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
                "Retry only the failed part of this Stage. Preserve valid existing work. "
                "Do not repeat the exact failed action without new evidence."
            )
        else:
            lines.append(
                "Recover this same Stage in the fresh/current session. Inspect current "
                "durable project state first and preserve valid existing work."
            )

        error = str(ctx.execution.previous_error or "").strip()
        task = ctx.task
        if task is not None and mode == "continue":
            lines.append(
                "current_task: "
                + json.dumps(
                    {
                        "title": getattr(task, "title", ""),
                        "description": getattr(task, "description", ""),
                        "deliverable": getattr(task, "deliverable", ""),
                        "acceptance_criteria": getattr(task, "acceptance_criteria", []),
                    },
                    ensure_ascii=False,
                )
            )
            last_output = str(getattr(task, "last_output", "") or "").strip()
            if last_output:
                lines.append("executor_evidence:\n" + last_output[-2500:])
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

        # Structured AI stages keep their semantic verdict in StageResult.data.
        # Their output may intentionally be empty, so top-level rollback must
        # transport reason/missing_items from data instead of relying on output.
        if previous is not None and previous.status == "fail":
            data = previous.data if isinstance(previous.data, dict) else {}
            if previous.kind == "review" and data.get("completed") is False:
                reason = str(data.get("reason") or "").strip()
                missing = data.get("missing_items")
                if reason:
                    parts.append("Review: " + reason[-2000:])
                if isinstance(missing, list) and missing:
                    parts.append(
                        "Review missing_items: "
                        + json.dumps(missing, ensure_ascii=False)[-2500:]
                    )
            elif previous.kind == "validation" and data.get("passed") is False:
                reason = str(data.get("reason") or "").strip()
                missing = data.get("missing_items")
                if reason:
                    parts.append("Validator: " + reason[-2000:])
                if isinstance(missing, list) and missing:
                    parts.append(
                        "Validator missing_items: "
                        + json.dumps(missing, ensure_ascii=False)[-2500:]
                    )

        if previous is not None and previous.status in {"fail", "error"}:
            detail = str(previous.error or previous.output or "").strip()
            if detail:
                parts.append(f"{previous.stage}: {detail[-2000:]}")
        return "\n".join(parts)

    def _prompt_seen(self, ctx: StageContext, client) -> bool:
        session = str(getattr(client, "session_id", "") or "")
        if not session:
            return False
        contracts = ctx.scratch.get("prompt_contracts")
        return (
            isinstance(contracts, dict)
            and contracts.get(self.name) == (self.spec.prompt, session)
        )

    def _remember_prompt(self, ctx: StageContext, client) -> None:
        session = str(getattr(client, "session_id", "") or "")
        if not session or not self.spec.prompt:
            return
        contracts = ctx.scratch.setdefault("prompt_contracts", {})
        if not isinstance(contracts, dict):
            contracts = {}
            ctx.scratch["prompt_contracts"] = contracts
        contracts[self.name] = (self.spec.prompt, session)

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
