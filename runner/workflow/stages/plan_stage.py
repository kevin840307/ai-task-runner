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
    run_state: str = "planning"
    min_tasks: int = MIN_PLANNED_TASKS
    repair_plan: bool = False


class PlanStage(BaseStage):
    """Generate only TODO data. Workflow topology remains static in YAML."""

    result_kind = "tasks"
    backend_mode = "planning"
    timeout_config_attr = "planning_timeout"

    def __init__(self, spec: PlanStageSpec) -> None:
        parser = lambda text, ctx: parse_plan_tasks(text, ctx, minimum=spec.min_tasks)
        super().__init__(replace(spec, parser=parser))

    def _original_prompt(self, ctx: StageContext, previous: StageResult | None) -> str:
        repair = self.spec.repair_plan
        values = build_stage_prompt_context(ctx, "repair_plan" if repair else "planning")
        planning = dict(values["planning"])
        planning["inspection_summary"] = (
            "" if repair else bounded_text(previous.output if previous else "", 12000)
        )
        values["planning"] = planning
        if not repair and ctx.ai_client.session_id and previous and previous.output:
            return render_prompt("stages/plan_finalize_same_session.md", values)
        return render_prompt("stages/plan_finalize.md", values)


def parse_plan_tasks(
    text: str, ctx: StageContext, *, minimum: int = MIN_PLANNED_TASKS
) -> list[Task]:
    """Parse Planning output through the same Task[] contract used by any producer."""
    return parse_result(
        text, lambda value: decode_tasks(value, cycle=ctx.state.cycle, minimum=minimum)
    )


PlanStage.spec_class = PlanStageSpec

__all__ = ["PlanStage", "PlanStageSpec", "parse_plan_tasks"]
