"""Planning Stage: render planning context and return a validated task plan."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ...ai.structured_output import parse_result, require_object, require_text, require_text_list
from ...config.defaults import MIN_PLANNED_TASKS
from ...errors import RunnerError
from ...prompts.context import build_stage_prompt_context
from ...prompts.loader import render_prompt
from ...runtime.run_state import Task
from ...utils import bounded_text
from .ai_stage import AIStage, AIStageSpec
from .contracts import StageContext, StageResult


@dataclass(frozen=True)
class PlanStageSpec(AIStageSpec):
    min_tasks: int = MIN_PLANNED_TASKS
    repair_plan: bool = False


class PlanStage(AIStage):
    """Generate one plan. Retry/routing/state installation are external policies."""

    def __init__(self, spec: PlanStageSpec) -> None:
        parser = lambda text, ctx: parse_plan_tasks(text, ctx, minimum=spec.min_tasks)
        super().__init__(replace(spec, parser=parser))

    def _original_prompt(self, ctx: StageContext, previous: StageResult | None) -> str:
        repair = self.spec.repair_plan
        values = build_stage_prompt_context(
            ctx,
            "repair_plan" if repair else "planning",
            previous,
        )
        planning = dict(values["planning"])
        planning.update({
            "source_instruction": (
                "Build the smallest repair plan directly from validator evidence. "
                "Do not inspect unrelated work."
                if repair
                else "Use only the supplied goal, progress, validator feedback, and inspection summary."
            ),
            "inspection_summary": "" if repair else bounded_text(previous.output if previous else "", 12000),
        })
        values["planning"] = planning
        if not repair and ctx.ai_client.session_id and previous and previous.output:
            return render_prompt("stages/plan_finalize_same_session.md", values)
        return render_prompt("stages/plan_finalize.md", values)


def parse_plan_tasks(text: str, ctx: StageContext, *, minimum: int = MIN_PLANNED_TASKS) -> list[Task]:
    """Parse a structured planning response into durable tasks."""

    def parse(value: Any) -> list[Task]:
        raw = require_object(value).get("tasks")
        if not isinstance(raw, list) or len(raw) < minimum:
            raise RunnerError(f"tasks must contain at least {minimum} items")
        tasks: list[Task] = []
        for index, item in enumerate(raw, 1):
            if not isinstance(item, dict):
                raise RunnerError(f"tasks[{index}] must be an object")
            tasks.append(Task(
                id=f"c{ctx.state.cycle:02d}-t{index:03d}",
                title=require_text(item.get("title"), f"tasks[{index}].title"),
                description=require_text(item.get("description"), f"tasks[{index}].description"),
                deliverable=require_text(item.get("deliverable"), f"tasks[{index}].deliverable"),
                acceptance_criteria=require_text_list(
                    item.get("acceptance_criteria", item.get("accept_criteria")),
                    f"tasks[{index}].acceptance_criteria",
                    allow_empty=False,
                ),
            ))
        return tasks

    return parse_result(text, parse)


__all__ = ["PlanStage", "PlanStageSpec", "parse_plan_tasks"]
