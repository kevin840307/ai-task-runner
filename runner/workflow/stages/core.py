"""Built-in semantic Stage profiles for planning, execution, review and orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from ...agent import parse_result, require_object, require_text
from ...config.defaults import MIN_PLANNED_TASKS
from ...errors import RunnerError
from ...prompting import build_stage_prompt_context, render_prompt
from ...runtime.run_state import Task
from ...utils import bounded_text
from ..results import decode_tasks
from .base_stage import (
    MODE_READONLY,
    MODE_WRITE,
    BaseStage,
    BaseStageSpec,
    SessionPolicy,
    StageContext,
    StageResult,
)


@dataclass(frozen=True)
class PlanStageSpec(BaseStageSpec):
    status: str = "AI 正在產生任務規劃"
    allow_project_read: bool = True
    run_state: str = "planning"
    prompt: str = "common/planning.md"
    fresh_session_on_start: bool = True
    min_tasks: int = MIN_PLANNED_TASKS


class PlanStage(BaseStage):
    result_kind = "tasks"
    backend_mode = "planning"
    timeout_config_attr = "planning_timeout"

    def __init__(self, spec: PlanStageSpec) -> None:
        parser = lambda text, ctx: parse_plan_tasks(
            text,
            ctx,
            minimum=spec.min_tasks,
        )
        super().__init__(replace(spec, parser=parser))

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        result = super().finish(ctx, result)
        if result.status != "pass":
            return result
        tasks = list(result.data or [])
        if not tasks or any(not isinstance(task, Task) for task in tasks):
            raise RunnerError("Plan Stage must produce validated tasks")
        return replace(
            result,
            data={
                "tasks": tasks,
                "stages": self._plan_child_stages(tasks),
            },
            kind="tasks",
        )

    @staticmethod
    def _plan_child_stages(tasks: list[Task]) -> list[dict[str, object]]:
        stages: list[dict[str, object]] = []
        for index, task in enumerate(tasks, 1):
            token = f"task_{index:03d}"
            execute = f"{token}_execute"
            review = f"{token}_review"
            stages.append({
                "name": execute,
                "type": "base",
                "profile": "execute",
                "task_id": task.id,
            })
            stages.append({
                "name": review,
                "type": "base",
                "profile": "review",
                "task_id": task.id,
                "task_complete": True,
                "error_policy": {"retries": 2},
                "max_failures": 3,
                "routes": {"fail": execute},
            })
        return stages

    def _original_prompt(
        self,
        ctx: StageContext,
        previous: StageResult | None,
    ) -> str:
        values = build_stage_prompt_context(ctx, "planning")
        planning = dict(values["planning"])
        planning["inspection_summary"] = bounded_text(
            previous.output if previous else "",
            12000,
        )
        values["planning"] = planning
        return self._augment_rendered_prompt(
            ctx,
            render_prompt(self.spec.prompt, values),
        )


def parse_plan_tasks(
    text: str,
    ctx: StageContext,
    *,
    minimum: int = MIN_PLANNED_TASKS,
) -> list[Task]:
    return parse_result(
        text,
        lambda value: decode_tasks(
            value,
            cycle=ctx.state.cycle,
            minimum=minimum,
        ),
    )


@dataclass(frozen=True)
class AIValidatorStageSpec(BaseStageSpec):
    status: str = "正在執行最終 AI 驗證"
    run_state: str = "validating"
    mode: str = MODE_READONLY
    actor: str = "validator"
    prompt: str = "common/ai_validator.md"
    ai_validator_yolo: bool | None = None
    structured_retries: int = 2
    structured_fresh_retries: int = 1
    fresh_session_each_run: bool = True


class AIValidatorStage(BaseStage):
    result_kind = "validation"
    parser_name = "validation"
    backend_mode = "review"
    client_cache_key = "ai_validation_client"
    runs_config_attr = "final_ai_validations"
    required_passes_config_attr = "final_ai_required_passes"
    result_flag = "passed"

    def _backend_mode(self, ctx: StageContext) -> str:
        return "validation" if self._yolo_enabled(ctx) else "review"

    def _augment_rendered_prompt(
        self,
        ctx: StageContext,
        prompt: str,
    ) -> str:
        mode = (
            "Runner final validation mode: YOLO verification is enabled. "
            "You may write small temporary verification scripts, run command-based checks, "
            "execute build/code/test commands, and run coverage validation when they materially improve evidence. "
            "Keep all scripts and generated artifacts in temporary locations or Runner work/debug/cache outputs, never in maintained project source. "
            "Do not modify production/source files, repair code, create tasks, search for tools, or ask for unavailable tools."
            if self._yolo_enabled(ctx)
            else
            "Runner final validation mode: read-only. Do not modify files, run shell/write/edit tools, create tasks, search for tools, or ask for unavailable tools. Use focused read-only checks when they materially resolve evidence."
        )
        instructions = str(
            getattr(ctx.config, "ai_validator_prompt", "") or ""
        ).strip()
        result = prompt.rstrip()
        if "Runner final validation mode:" not in result:
            result += "\n\n" + mode + "\n"
        else:
            result += "\n"
        if instructions and instructions not in result:
            result += (
                "\nRunner-provided AI validation resource (required):\n"
                + instructions
                + "\n"
            )
        return result

    def _yolo_enabled(self, ctx: StageContext) -> bool:
        value = self.spec.ai_validator_yolo
        if value is None:
            value = bool(getattr(ctx.config, "ai_validator_yolo", False))
        return bool(value)

    def enabled(self, ctx: StageContext) -> bool:
        return bool(
            ctx.config.workflow_explicit
            or ctx.validator_is_ai
            or ctx.config.ai_validator_prompt.strip()
        )



@dataclass(frozen=True)
class HandoffStageSpec(BaseStageSpec):
    status: str = "AI 正在選擇下一個 Agent"
    run_state: str = "handoff"
    mode: str = MODE_READONLY
    actor: str = "scheduler"
    prompt: str = "common/handoff.md"
    targets: list[str] = field(default_factory=list)
    structured_retries: int = 2
    session_policy: SessionPolicy = "role"


class HandoffStage(BaseStage):
    result_kind = "handoff"
    backend_mode = "review"

    def __init__(self, spec: HandoffStageSpec) -> None:
        allowed = tuple(spec.targets)

        def parse_handoff(text: str, ctx: StageContext):
            def parse(value):
                obj = require_object(value)
                target = require_text(obj.get("target"), "handoff.target")
                reason = require_text(obj.get("reason"), "handoff.reason")
                if target not in allowed:
                    raise RunnerError(
                        f"handoff.target must be one of: {', '.join(allowed)}"
                    )
                return {"target": target, "reason": reason}

            return parse_result(text, parse)

        super().__init__(replace(spec, parser=parse_handoff))

    def _with_immutable_protocol(self, prompt: str) -> str:
        allowed = ", ".join(self.spec.targets)
        base = super()._with_immutable_protocol(prompt).rstrip()
        return (
            base
            + "\n\n[RUNNER_IMMUTABLE_HANDOFF_PROTOCOL]\n"
            + "Choose exactly one next Stage from the allowed targets. "
            + "Do not execute that Stage yourself.\n"
            + f"Allowed targets: {allowed}\n"
            + 'Return exactly one JSON object and no markdown: '
            + '{"target":"stage_name","reason":"concise reason"}\n'
            + "[/RUNNER_IMMUTABLE_HANDOFF_PROTOCOL]\n"
        )

PlanStage.spec_class = PlanStageSpec
HandoffStage.spec_class = HandoffStageSpec
AIValidatorStage.spec_class = AIValidatorStageSpec

__all__ = [
    "AIValidatorStage",
    "AIValidatorStageSpec",
    "HandoffStage",
    "HandoffStageSpec",
    "PlanStage",
    "PlanStageSpec",
    "parse_plan_tasks",
]
