"""Prompt builders for the bundled workflow only."""
from __future__ import annotations

import json
from typing import Any

from ..config.defaults import MIN_PLANNED_TASKS
from ..model.prompt import always_instructions
from ..prompts import STAGE_PACKAGE
from ..runtime.state import RunState, Task
from ..utils import bounded_text
from ..utils.templates import append_resource, render_resource
from .stages.base import StageContext, StageResult

Outcome = StageResult


def flow_template(name: str, values: dict[str, Any] | None = None) -> str:
    return render_resource(STAGE_PACKAGE, f"{name}.md", values)


def flow_fragment(prompt: str, name: str) -> str:
    return append_resource(prompt, STAGE_PACKAGE, f"{name}.md")


def _planning_context(ctx: StageContext) -> dict[str, Any]:
    state = ctx.state
    progress_data = {
        "cycle": state.cycle,
        "validator_feedback": state.validator_output[-8000:],
        "replan_feedback": state.replan_feedback[-4000:],
        "completed_tasks": [task.title for task in state.tasks if task.status == "completed"][-20:],
        "review_skipped_tasks": [
            {"id": task.id, "title": task.title, "reason": task.review_skip_reason}
            for task in state.tasks if task.review_skipped
        ][-20:],
    }
    return {
        "planning_rules": flow_template("planning_rules", {"work": ctx.work}) + always_instructions(ctx.root),
        "goal": state.goal,
        "root": ctx.root,
        "progress_json": json.dumps(progress_data, ensure_ascii=False),
        "work_dir": ctx.work,
        "minimum_tasks": MIN_PLANNED_TASKS,
        "planning_mode": "initial" if state.cycle == 1 else "repair",
    }


def planning_prompt(ctx: StageContext, previous: Outcome | None) -> str:
    summary = previous.output if previous else ""
    if ctx.model.session_id and summary:
        return flow_fragment(flow_template("plan_finalize_same_session", {
            "minimum_tasks": MIN_PLANNED_TASKS,
            "planning_mode": "initial" if ctx.state.cycle == 1 else "repair",
        }), "plan_output_contract")
    return flow_fragment(flow_template("plan_finalize", {
        **_planning_context(ctx),
        "source_instruction": "Use only the supplied goal, progress, validator feedback, and inspection summary.",
        "inspection_summary": bounded_text(summary, 12000),
    }), "plan_output_contract")


def repair_plan_prompt(ctx: StageContext, previous: Outcome | None) -> str:
    ctx.model.session_id = ""
    return flow_fragment(flow_template("plan_finalize", {
        **_planning_context(ctx),
        "source_instruction": "Build the smallest repair plan directly from validator evidence. Do not inspect unrelated work.",
        "inspection_summary": "",
    }), "plan_output_contract")


def _task_spec(task: Task) -> dict[str, Any]:
    return {
        "title": task.title,
        "description": task.description,
        "deliverable": task.deliverable,
        "acceptance_criteria": task.acceptance_criteria,
    }


def _shared_constraints(state: RunState) -> list[str]:
    tasks = [task for task in state.tasks if task.id.startswith(f"c{state.cycle:02d}-")]
    if not tasks:
        return []
    common = set(tasks[0].acceptance_criteria)
    for task in tasks[1:]:
        common.intersection_update(task.acceptance_criteria)
    return [item for item in tasks[0].acceptance_criteria if item in common][:8]


def review_prompt(ctx: StageContext, previous: Outcome | None) -> str:
    task = ctx.require_task("review")
    return flow_fragment(flow_template("review", {
        "always_instructions": always_instructions(ctx.root),
        "global_constraints_json": json.dumps(_shared_constraints(ctx.state), ensure_ascii=False),
        "task_json": json.dumps(_task_spec(task), ensure_ascii=False),
        "output": task.last_output[-3000:],
        "validator_section": ("\nLatest validator feedback to consider:\n" + bounded_text(ctx.state.validator_output, 2000) + "\n") if ctx.state.validator_output.strip() else "",
    }), "review_output_contract")




PROMPT_BUILDERS = {
    "planning_prompt": planning_prompt,
    "repair_plan_prompt": repair_plan_prompt,
    "review_prompt": review_prompt,
}

__all__ = ["PROMPT_BUILDERS", "flow_template", "flow_fragment"]
