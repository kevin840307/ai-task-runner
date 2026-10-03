"""Planning Stage: produce validated tasks plus producer-defined child Stages."""
from __future__ import annotations

from dataclasses import dataclass, replace

from ...agent import parse_result
from ...config.defaults import MIN_PLANNED_TASKS
from ...errors import RunnerError
from ...prompting import build_stage_prompt_context, render_prompt
from ...runtime.run_state import Task
from ...utils import bounded_text
from ..profiles import apply_ai_profile_defaults
from ..results import decode_tasks
from .base_stage import BaseStage, BaseStageSpec, StageContext, StageResult


@dataclass(frozen=True)
class PlanStageSpec(BaseStageSpec):
    status: str = "AI 正在產生任務規劃"
    allow_project_read: bool = True
    run_state: str = "planning"
    prompt: str = "common/planning.md"
    fresh_session_on_start: bool = True
    min_tasks: int = MIN_PLANNED_TASKS


class PlanStage(BaseStage):
    ui_title = "Plan"
    ui_description = "Plan work and generate a producer-defined dynamic child Workflow."
    ui_category = "build"
    result_kind = "tasks"
    protocol_kind = "plan_tasks"
    backend_mode = "planning"
    timeout_config_attr = "planning_timeout"

    def __init__(self, spec: PlanStageSpec) -> None:
        parser = lambda text, ctx: parse_plan_tasks(text, ctx, minimum=spec.min_tasks)
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
            data={"tasks": tasks, "stages": self._plan_child_stages(tasks)},
            kind="tasks",
        )

    @staticmethod
    def _plan_child_stages(tasks: list[Task]) -> list[dict[str, object]]:
        stages: list[dict[str, object]] = []
        for index, task in enumerate(tasks, 1):
            token = f"task_{index:03d}"
            execute = f"{token}_execute"
            review = f"{token}_review"
            stages.extend([
                {
                    "name": execute,
                    "type": "base",
                    "profile": "execute",
                    "task_id": task.id,
                },
                {
                    "name": review,
                    "type": "base",
                    "profile": "review",
                    "task_id": task.id,
                    "task_complete": True,
                    "routes": {"fail": execute},
                },
            ])
        return [apply_ai_profile_defaults(stage) for stage in stages]

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
        lambda value: decode_tasks(value, cycle=ctx.state.cycle, minimum=minimum),
    )


PlanStage.spec_class = PlanStageSpec

__all__ = ["PlanStage", "PlanStageSpec", "parse_plan_tasks"]
