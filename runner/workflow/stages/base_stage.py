"""Generic AI-backed Stage. Retry routing and UI lifecycle live outside it."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from ...agent import backend_names, configure_ai_client, create_ai_client, sandbox_supported, structured_call
from ...config.defaults import MAX_MODEL_NAME_CHARS
from ...errors import ConfigurationError, RunnerError
from ...prompting import append_stage_protocol, build_stage_prompt_context, render_prompt
from ..profiles import profile_defaults, profile_names
from ..contracts import MODE_READONLY, MODE_WRITE, StageContext, StageMode, StageResult

AIStageProfile = Literal["generic", "execute", "review"]
SessionPolicy = Literal["auto", "main", "role", "fresh"]


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
    runs: int | None = None
    required_passes: int | None = None
    readonly_safety: str = ""
    track_changes: bool = False
    tolerate_restored_changes: bool = False
    timeout: float | None = None
    backend: str = ""
    model: str = ""
    session_policy: SessionPolicy = "auto"
    produces: str = ""
    max_failures: int | None = None



class BaseStage:
    ui_title = "AI Stage"
    ui_description = "General AI Stage; choose Generic, Execute, or Review behavior profile."
    ui_category = "build"
    """Perform one or more AI interactions and return only resulting facts."""

    result_kind = "generic"
    protocol_kind = ""
    parser_name = ""
    backend_mode = "runtime"
    timeout_config_attr = "agent_timeout"
    runs_config_attr = ""
    required_passes_config_attr = ""
    client_cache_key = ""
    result_flag = ""

    def __init__(self, spec: BaseStageSpec) -> None:
        profile = str(spec.profile or "generic")
        backend = str(spec.backend or "").strip()
        model = str(spec.model or "").strip()
        if backend and backend not in backend_names():
            raise ConfigurationError(f"AI Stage {spec.name} backend is unsupported: {backend}")
        if len(model) > MAX_MODEL_NAME_CHARS or any(ord(ch) < 32 for ch in model):
            raise ConfigurationError(f"AI Stage {spec.name} model is invalid")
        if (backend or model) and spec.session_policy == "main":
            raise ConfigurationError(
                f"AI Stage {spec.name} cannot combine backend/model override with session_policy=main"
            )
        if profile not in profile_names():
            raise ConfigurationError(
                f"AI Stage {spec.name} profile must be one of: {', '.join(profile_names())}"
            )
        defaults = profile_defaults(profile)
        if profile == "generic":
            spec = replace(
                spec,
                prompt=spec.prompt or str(defaults.get("prompt", "")),
            )
        elif profile == "execute":
            spec = replace(
                spec,
                status=spec.status if spec.status != "AI Stage" else str(defaults.get("status", "AI Stage")),
                prompt=spec.prompt or str(defaults.get("prompt", "")),
                run_state=spec.run_state or str(defaults.get("run_state", "")),
                mode=MODE_WRITE,
                actor="executor" if spec.actor == "ai" else spec.actor,
                allow_project_read=True,
                track_changes=True if not spec.track_changes else spec.track_changes,
            )
            self.result_kind = "task"
        elif profile == "review":
            from ..results import PARSERS
            spec = replace(
                spec,
                status=spec.status if spec.status != "AI Stage" else str(defaults.get("status", "AI Stage")),
                prompt=spec.prompt or str(defaults.get("prompt", "")),
                run_state=spec.run_state or str(defaults.get("run_state", "")),
                mode=MODE_READONLY,
                allow_project_read=True,
                readonly_safety=spec.readonly_safety or "observe",
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
            if self.spec.session_policy == "fresh" and not self._run_pending:
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
        if client is ctx.ai_client:
            configure_ai_client(
                client,
                ctx.config,
                backend_mode,
                allow_project_read=spec.allow_project_read,
            )
        else:
            client.set_runtime(
                backend_mode,
                allow_project_read=spec.allow_project_read,
                sandbox=getattr(ctx.config, "sandbox", False),
            )
        try:
            prompt = self._prompt(ctx, previous, client)

            def ask(text: str) -> str:
                raw = self._ask(ctx, client, text)
                # A successful model response proves this session already saw
                # the Stage context even if structured parsing later rejects
                # the response. Checkpoint transport state here so technical
                # retry can send only the shared recovery delta.
                self._remember_prompt(ctx, client)
                self._persist_session(ctx, client)
                return raw

            def call() -> tuple[str, Any]:
                if spec.parser is None:
                    raw = ask(prompt)
                    return raw, raw
                data = structured_call(
                    prompt,
                    lambda text: spec.parser(text, ctx),
                    ask,
                    retries=spec.structured_retries,
                )
                return "", data

            output, data = call()
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
        elif self._uses_stage_session():
            ctx.state.stage_sessions.pop(self.name, None)
        contracts = ctx.scratch.get("prompt_contracts")
        if isinstance(contracts, dict) and previous:
            identity = self._prompt_contract_identity()
            if contracts.get(identity) == previous:
                contracts.pop(identity, None)
        ctx.save_state()
        return previous

    def _timeout(self, ctx: StageContext) -> float:
        if self.spec.timeout is not None:
            return float(self.spec.timeout)
        return float(getattr(ctx.config, self.timeout_config_attr))

    def _backend_mode(self, ctx: StageContext) -> str:
        return self.backend_mode

    def _uses_stage_session(self) -> bool:
        return self.spec.session_policy == "role" or (
            self.spec.session_policy == "auto"
            and bool(str(self.spec.backend or "").strip() or str(self.spec.model or "").strip())
        )

    def _client(self, ctx: StageContext):
        policy = self.spec.session_policy
        if policy == "main":
            return ctx.ai_client

        if policy in {"role", "fresh"} or self._uses_stage_session():
            key = f"stage_session:{self.name}"
            client = ctx.scratch.get(key)
            if client is None:
                backend_override = str(self.spec.backend or "").strip()
                if (
                    backend_override
                    and bool(getattr(ctx.config, "sandbox", False))
                    and not sandbox_supported(backend_override)
                ):
                    raise ConfigurationError(
                        f"AI Stage {self.name} backend does not support sandbox mode: {backend_override}"
                    )
                client = create_ai_client(
                    ctx.config,
                    ctx.root,
                    ctx.work / "debug",
                    mode=self._backend_mode(ctx),
                    timeout=self._timeout(ctx),
                    allow_project_read=self.spec.allow_project_read,
                    backend_override=backend_override,
                    model_override=str(self.spec.model or "").strip(),
                    session_id=(
                        ctx.state.stage_sessions.get(self.name, "")
                        if self._uses_stage_session()
                        else ""
                    ),
                )
                ctx.scratch[key] = client
            return client

        key = self.client_cache_key
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
        if self._uses_stage_session():
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
            and contracts.get(self._prompt_contract_identity()) == session
        )

    def _remember_prompt(self, ctx: StageContext, client) -> None:
        session = str(getattr(client, "session_id", "") or "")
        if not session or not self.spec.prompt:
            return
        contracts = ctx.scratch.setdefault("prompt_contracts", {})
        if not isinstance(contracts, dict):
            contracts = {}
            ctx.scratch["prompt_contracts"] = contracts
        contracts[self._prompt_contract_identity()] = session

    def _prompt_contract_identity(self) -> tuple[str, str, str, str, str]:
        """Static prompt identity reusable across dynamically generated sibling Stages."""
        return (
            str(self.spec.profile or "generic"),
            str(self.spec.prompt or ""),
            str(self.spec.instructions or ""),
            str(self.spec.backend or ""),
            str(self.spec.model or ""),
        )

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
        return append_stage_protocol(prompt, self.protocol_kind or self.result_kind)


BaseStage.spec_class = BaseStageSpec

__all__ = ["BaseStage", "BaseStageSpec"]
