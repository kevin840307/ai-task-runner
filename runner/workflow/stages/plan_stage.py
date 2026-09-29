"""Planning Stage: produce durable TODOs only; the SOP decides how each TODO runs."""
from __future__ import annotations

from dataclasses import dataclass, replace
from ...ai.structured_output import parse_result
from ...config.defaults import MIN_PLANNED_TASKS
from ...prompts.context import build_stage_prompt_context
from ...prompts.loader import render_prompt
from ...runtime.run_state import Task
from ..task_output import decode_tasks
from ...utils.text import bounded_text
from .base_stage import BaseStage, BaseStageSpec
from .contracts import StageContext, StageResult


@dataclass(frozen=True)
class PlanStageSpec(BaseStageSpec):
    status: str = "AI 正在產生任務規劃"
    allow_project_read: bool = True
    run_state: str = "planning"
    prompt: str = "common/planning.md"
    fresh_session_on_start: bool = True
    min_tasks: int = MIN_PLANNED_TASKS


class PlanStage(BaseStage):
    """Generate only TODO data. Workflow topology remains static in YAML."""

    result_kind = "tasks"
    backend_mode = "planning"
    timeout_config_attr = "planning_timeout"

    def __init__(self, spec: PlanStageSpec) -> None:
        parser = lambda text, ctx: parse_plan_tasks(text, ctx, minimum=spec.min_tasks)
        super().__init__(replace(spec, parser=parser))

    def _original_prompt(self, ctx: StageContext, previous: StageResult | None) -> str:
        values = build_stage_prompt_context(ctx, "planning")
        planning = dict(values["planning"])
        planning["inspection_summary"] = bounded_text(
            previous.output if previous else "", 12000
        )
        values["planning"] = planning
        prompt = render_prompt(self.spec.prompt, values)
        return self._augment_rendered_prompt(ctx, prompt)


def parse_plan_tasks(
    text: str, ctx: StageContext, *, minimum: int = MIN_PLANNED_TASKS
) -> list[Task]:
    """Parse Planning output through the same Task[] contract used by any producer."""
    return parse_result(
        text, lambda value: decode_tasks(value, cycle=ctx.state.cycle, minimum=minimum)
    )


PlanStage.spec_class = PlanStageSpec

__all__ = ["PlanStage", "PlanStageSpec", "parse_plan_tasks"]
