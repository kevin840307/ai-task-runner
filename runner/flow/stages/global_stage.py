"""Generic model-backed Stage. Hooks, retry routing and UI lifecycle live outside it."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from typing import Any, Literal

from ...errors import ConfigurationError
from ...model.prompt import always_instructions, structured_retry_prompt
from ...model.model import configure_model, create_model
from ...model.response import structured_call
from ...prompts import PROMPT_ROOT
from ...utils.templates import render_prompt_file
from .base import StageContext, StageResult

PromptBuilder = Callable[[StageContext, StageResult | None], str]
ResultParser = Callable[[str, StageContext], Any]
StatusResolver = Callable[[Any], Literal["pass", "fail"]]
Condition = Callable[[StageContext], bool]
ResultHandler = Callable[[StageContext, StageResult], StageResult]


@dataclass(frozen=True)
class GlobalStageSpec:
    name: str
    status: str
    prompt: str = ""
    prompt_builder: PromptBuilder | None = None
    detail: str = ""
    run_state: str = ""
    mode: Literal["readonly", "write"] = "readonly"
    actor: str = "model"
    model_mode: str = "runtime"
    allow_project_read: bool = False
    parser: ResultParser | None = None
    result_status: StatusResolver | None = None
    condition: Condition | None = None
    structured_retries: int = 1
    structured_fresh_retries: int = 0
    retry: int | None = None
    retry_attr: str = ""
    reviews: int = 1
    reviews_attr: str = ""
    track_changes: bool = False
    tolerate_restored_changes: bool = False
    timeout_attr: str = "agent_timeout"
    fresh_model: bool = False
    fresh_each_review: bool = False
    model_key: str = ""
    skip_on_error: bool = False
    result_handler: ResultHandler | None = None
    plan_only_stop: bool = False


class GlobalStage:
    """Perform one AI interaction and return only the resulting facts."""

    def __init__(self, spec: GlobalStageSpec) -> None:
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

    def run(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        """Perform one Stage attempt. Retry/Hook/Event are owned by StageExecutor."""
        if self.spec.condition is not None and not self.spec.condition(ctx):
            return StageResult(self.name, "pass", output="STAGE_SKIPPED", skipped=True)
        reviews = int(getattr(ctx.args, self.spec.reviews_attr)) if self.spec.reviews_attr else self.spec.reviews
        if reviews <= 1:
            return self._run_once(ctx, previous)

        results = []
        for _ in range(reviews):
            if self.spec.fresh_each_review:
                self._model(ctx).session_id = ""
            results.append(self._run_once(ctx, previous))
        passed = sum(item.status == "pass" for item in results)
        required = reviews // 2 + 1
        status = "pass" if passed >= required else "fail"
        return StageResult(
            self.name,
            status,
            output=json.dumps({"passed": status == "pass", "passes": passed, "required_passes": required, "reviews": [item.data for item in results]}, ensure_ascii=False),
            data=[item.data for item in results],
        )


    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        """Convert final execution facts into state/follow-up facts for the pipeline."""
        if self.spec.result_handler is None:
            return result
        return self.spec.result_handler(ctx, result)

    def _run_once(self, ctx: StageContext, previous: StageResult | None = None) -> StageResult:
        spec = self.spec
        model = self._model(ctx)
        configure_model(model, ctx.args, spec.model_mode, allow_project_read=spec.allow_project_read)
        try:
            prompt = self._prompt(ctx, previous, model)

            def call() -> tuple[str, Any]:
                if spec.parser is None:
                    raw = self._ask(ctx, model, prompt)
                    return raw, raw
                data = structured_call(
                    prompt,
                    lambda text: spec.parser(text, ctx),
                    lambda text: self._ask(ctx, model, text),
                    retries=spec.structured_retries,
                    retry_prompt=lambda error: always_instructions(ctx.root) + structured_retry_prompt(error),
                    fresh_ask=lambda: self._structured_fresh_ask(ctx, model, previous),
                    fresh_retries=spec.structured_fresh_retries,
                )
                return "", data

            output, data = model.invoke(
                call,
                spec.status,
                spec.detail,
                ctx.args.retry_wait,
                ctx.args.retry_max_wait,
                max_elapsed=ctx.args.api_wait_timeout,
            )
            status = spec.result_status(data) if spec.result_status else "pass"
        finally:
            if model is ctx.model:
                configure_model(model, ctx.args, "runtime")

        return StageResult(self.name, status, output=output, data=data)

    def _structured_fresh_ask(self, ctx: StageContext, model, previous: StageResult | None) -> str:
        model.session_id = ""
        original = self._original_prompt(ctx, previous)
        return self._ask(ctx, model, self._fresh_session_prompt(ctx, original))

    def _ask(self, ctx: StageContext, model, prompt: str) -> str:
        return model.ask(
            prompt,
            idle_timeout_after_change=ctx.args.agent_idle_after_change_timeout,
            change_detected=ctx.execution.change_detected,
            timeout=getattr(ctx.args, self.spec.timeout_attr),
        )

    def _model(self, ctx: StageContext):
        spec = self.spec
        if not spec.model_key:
            return ctx.model
        model = ctx.scratch.get(spec.model_key)
        if model is None and spec.fresh_model:
            model = create_model(
                ctx.args,
                ctx.root,
                ctx.work / "debug",
                mode=spec.model_mode,
                timeout=getattr(ctx.args, spec.timeout_attr),
            )
            ctx.scratch[spec.model_key] = model
        return model or ctx.model

    def _prompt(self, ctx: StageContext, previous: StageResult | None, model) -> str:
        original = self._original_prompt(ctx, previous)
        mode = ctx.execution.retry_mode
        if mode == "initial":
            return original
        if mode == "same" and getattr(model, "session_id", ""):
            return self._same_session_prompt(ctx)
        return self._fresh_session_prompt(ctx, original)

    def _original_prompt(self, ctx: StageContext, previous: StageResult | None) -> str:
        spec = self.spec
        if spec.prompt_builder is not None:
            return spec.prompt_builder(ctx, previous)
        if not spec.prompt:
            raise ConfigurationError(f"AI stage {spec.name} requires prompt or prompt_builder")
        return render_prompt_file(
            spec.prompt,
            ctx.template_values(spec.name, previous),
            base=PROMPT_ROOT,
        )

    def _same_session_prompt(self, ctx: StageContext) -> str:
        loop_note = "\nDo not repeat the exact failed action; use a different approach.\n" if "loop" in ctx.execution.previous_error.lower() else ""
        return (
            always_instructions(ctx.root)
            + "\nContinue the current task. Fix the previous failure and finish it. "
              "Preserve valid existing work and do not restart unrelated work.\n"
            + loop_note
        )

    def _fresh_session_prompt(self, ctx: StageContext, original: str) -> str:
        task = ctx.task
        task_text = "" if task is None else json.dumps({
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "deliverable": task.deliverable,
            "acceptance_criteria": task.acceptance_criteria,
        }, ensure_ascii=False)
        return (
            always_instructions(ctx.root)
            + "\nYou are continuing an interrupted task in a new session.\n"
            + f"Original specification:\n{ctx.state.goal}\n\n"
            + (f"Current task:\n{task_text}\n\n" if task_text else "")
            + "Inspect the CURRENT project state first. Preserve valid existing work. "
              "Complete only the current stage/task.\n\n"
            + f"Stage instructions:\n{original}"
        )


__all__ = ["GlobalStage", "GlobalStageSpec", "ResultHandler"]
