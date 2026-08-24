"""Planning Stage: one AI attempt that returns a validated task plan."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ...config.defaults import MIN_PLANNED_TASKS
from ...errors import RunnerError
from ...model.response import parse_result, require_object, require_text, require_text_list
from ...runtime.state import Task
from .global_stage import GlobalStage, GlobalStageSpec
from .base import StageContext


@dataclass(frozen=True)
class PlanStageSpec(GlobalStageSpec):
    min_tasks: int = MIN_PLANNED_TASKS


class PlanStage(GlobalStage):
    """Generate one plan. Retry/routing/state installation are external policies."""

    def __init__(self, spec: PlanStageSpec) -> None:
        parser = lambda text, ctx: parse_plan_tasks(text, ctx, minimum=spec.min_tasks)
        super().__init__(replace(spec, parser=parser))


def parse_plan_tasks(text: str, ctx: StageContext, *, minimum: int = MIN_PLANNED_TASKS) -> list[Task]:
    """Shared plan parser used by the special PlanStage and legacy default flow."""

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
                    f"tasks[{index}].acceptance_criteria", allow_empty=False,
                ),
            ))
        return tasks

    return parse_result(text, parse)


__all__ = ["PlanStage", "PlanStageSpec", "parse_plan_tasks"]
