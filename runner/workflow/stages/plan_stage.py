"""Planning Stage: produce durable tasks and their dynamic Stage sequence."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

from ...ai.structured_output import (
    parse_result,
    require_object,
    require_text,
    require_text_list,
)
from ...config.defaults import MIN_PLANNED_TASKS
from ...errors import RunnerError
from ...prompts.context import build_stage_prompt_context
from ...prompts.loader import render_prompt
from ...runtime.run_state import Task
from ...utils import bounded_text
from .base_stage import BaseStage, BaseStageSpec
from .contracts import MODE_READONLY, MODE_WRITE, StageContext, StageResult


@dataclass(frozen=True)
class PlanStageSpec(BaseStageSpec):
    min_tasks: int = MIN_PLANNED_TASKS
    repair_plan: bool = False
    planner_stages: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)


class PlanStage(BaseStage):
    """Generate tasks plus the Stage sequence that executes each task."""

    def __init__(self, spec: PlanStageSpec) -> None:
        parser = lambda text, ctx: parse_plan_tasks(
            text,
            ctx,
            minimum=spec.min_tasks,
            planner_stages=spec.planner_stages,
        )
        super().__init__(replace(spec, parser=parser))

    def finish(self, ctx: StageContext, result: StageResult) -> StageResult:
        result = super().finish(ctx, result)
        if result.status != "pass" or not isinstance(result.data, list):
            return result

        tasks = [task for task in result.data if isinstance(task, Task)]
        return replace(
            result,
            next_steps=build_task_steps(tasks, self.spec.planner_stages),
        )

    def _original_prompt(self, ctx: StageContext, previous: StageResult | None) -> str:
        repair = self.spec.repair_plan
        values = build_stage_prompt_context(
            ctx,
            "repair_plan" if repair else "planning",
        )
        planning = dict(values["planning"])
        planning["inspection_summary"] = (
            "" if repair else bounded_text(previous.output if previous else "", 12000)
        )
        planning["available_stages"] = [
            {
                "name": name,
                "status": definition.get("status", ""),
                "mode": definition.get("mode", MODE_READONLY),
                "review": definition.get("result_handler") == "review",
            }
            for name, definition in self.spec.planner_stages.items()
        ]
        values["planning"] = planning
        if not repair and ctx.ai_client.session_id and previous and previous.output:
            return render_prompt("stages/plan_finalize_same_session.md", values)
        return render_prompt("stages/plan_finalize.md", values)


def build_task_steps(
    tasks: list[Task],
    planner_stages: dict[str, dict[str, Any]],
    *,
    start: int = 0,
) -> list[dict[str, Any]]:
    """Build executable definitions from the durable per-task Stage plan."""
    result: list[dict[str, Any]] = []
    for task_index in range(start, len(tasks)):
        task = tasks[task_index]
        for step_index, name in enumerate(task.steps):
            definition = deepcopy(planner_stages[name])
            definition["_task_index"] = task_index
            definition["_task_last"] = step_index == len(task.steps) - 1
            result.append(definition)
    return result



def parse_plan_tasks(
    text: str,
    ctx: StageContext,
    *,
    minimum: int = MIN_PLANNED_TASKS,
    planner_stages: dict[str, dict[str, Any]] | None = None,
) -> list[Task]:
    """Parse a structured planning response into durable executable tasks."""
    available = planner_stages or {}
    review_stages = {
        name
        for name, definition in available.items()
        if definition.get("result_handler") == "review"
    }
    write_stages = {
        name
        for name, definition in available.items()
        if definition.get("mode") == MODE_WRITE
    }

    def parse(value: Any) -> list[Task]:
        raw = require_object(value).get("tasks")
        if not isinstance(raw, list) or len(raw) < minimum:
            raise RunnerError(f"tasks must contain at least {minimum} items")
        tasks: list[Task] = []
        for index, item in enumerate(raw, 1):
            if not isinstance(item, dict):
                raise RunnerError(f"tasks[{index}] must be an object")
            steps = require_text_list(
                item.get("steps"),
                f"tasks[{index}].steps",
                allow_empty=False,
            )
            unknown = [name for name in steps if name not in available]
            if unknown:
                raise RunnerError(
                    f"tasks[{index}].steps contains unavailable Stage: {unknown[0]}"
                )
            if review_stages and steps[-1] not in review_stages:
                raise RunnerError(
                    f"tasks[{index}].steps must end with a review Stage"
                )
            if write_stages and not any(name in write_stages for name in steps):
                raise RunnerError(
                    f"tasks[{index}].steps must include a write Stage"
                )
            tasks.append(
                Task(
                    id=f"c{ctx.state.cycle:02d}-t{index:03d}",
                    title=require_text(item.get("title"), f"tasks[{index}].title"),
                    description=require_text(
                        item.get("description"), f"tasks[{index}].description"
                    ),
                    deliverable=require_text(
                        item.get("deliverable"), f"tasks[{index}].deliverable"
                    ),
                    acceptance_criteria=require_text_list(
                        item.get("acceptance_criteria", item.get("accept_criteria")),
                        f"tasks[{index}].acceptance_criteria",
                        allow_empty=False,
                    ),
                    steps=steps,
                )
            )
        return tasks

    return parse_result(text, parse)


PlanStage.spec_class = PlanStageSpec

__all__ = [
    "PlanStage",
    "PlanStageSpec",
    "build_task_steps",
    "parse_plan_tasks",
]
