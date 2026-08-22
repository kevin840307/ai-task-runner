"""Prompt template loading and prompt builders."""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from string import Template as PromptTemplate
from typing import Any

from ..errors import RunnerError
from ..models import RunState, Task
from ..safety.policy import instructions

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
MAX_PROMPT_HISTORY_ITEMS = 20


def bounded_text(text: str, limit: int) -> str:
    """Keep useful start and end context without letting state grow forever."""
    if len(text) <= limit:
        return text
    if limit < 100:
        return text[-limit:]
    head = limit // 2
    marker = f"\n... omitted {len(text) - limit} characters ...\n"
    tail = max(0, limit - head - len(marker))
    return text[:head] + marker + text[-tail:]


def render_prompt_template(name: str, values: dict[str, Any]) -> str:
    path = PROMPT_DIR / name
    try:
        template = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RunnerError(f"missing prompt template: {path}") from error
    return PromptTemplate(template).safe_substitute(
        {key: str(value) for key, value in values.items()}
    )


def _always_instructions(root: Path) -> str:
    text = instructions(root, "always")
    return f"\nUser-enforced instructions (apply to this call):\n{text}\n" if text else ""


def rules(root: Path, protected: Sequence[Path]) -> str:
    protected_names = "\n".join(f"- {path}" for path in protected)
    return render_prompt_template(
        "rules.md",
        {"root": root, "protected_names": protected_names},
    ) + _always_instructions(root)


def planning_rules(work: Path, root: Path) -> str:
    return render_prompt_template("planning_rules.md", {"work": work}) + _always_instructions(root)


def task_spec(task: Task) -> dict[str, Any]:
    return {
        "title": task.title,
        "description": task.description,
        "deliverable": task.deliverable,
        "acceptance_criteria": task.acceptance_criteria,
    }



def shared_task_constraints(state: RunState) -> list[str]:
    """Return concise goal-wide constraints repeated across every planned TODO."""
    tasks = [
        task for task in state.tasks
        if task.id.startswith(f"c{state.cycle:02d}-")
    ]
    if not tasks:
        return []
    common = set(tasks[0].acceptance_criteria)
    for task in tasks[1:]:
        common.intersection_update(task.acceptance_criteria)
    return [item for item in tasks[0].acceptance_criteria if item in common][:8]

def completed_titles(state: RunState) -> list[str]:
    return [
        task.title for task in state.tasks if task.status == "completed"
    ][-MAX_PROMPT_HISTORY_ITEMS:]


def skipped_review_tasks(state: RunState) -> list[dict[str, Any]]:
    return [
        {
            "id": task.id,
            "title": task.title,
            "reason": task.review_skip_reason,
        }
        for task in state.tasks
        if task.review_skipped
    ][-MAX_PROMPT_HISTORY_ITEMS:]


def _planning_context(
    goal: str,
    root: Path,
    state: RunState,
    work: Path | None,
) -> dict[str, Any]:
    work_dir = work or root / ".ai-task-runner"
    progress = {
        "cycle": state.cycle,
        "validator_feedback": state.validator_output[-8000:],
        "completed_tasks": completed_titles(state),
        "review_skipped_tasks": skipped_review_tasks(state),
    }
    return {
        "planning_rules": planning_rules(work_dir, root),
        "goal": goal,
        "root": root,
        "progress_json": json.dumps(progress, ensure_ascii=False),
        "work_dir": work_dir,
        "minimum_tasks": 6 if state.cycle == 1 else 1,
        "planning_mode": "initial" if state.cycle == 1 else "repair",
    }


def plan_understand_prompt(
    goal: str,
    root: Path,
    state: RunState,
    protected: Sequence[Path],
    work: Path | None = None,
    planning_feedback: str = "",
) -> str:
    context = _planning_context(goal, root, state, work)
    return render_prompt_template(
        "plan_understand.md",
        {
            **context,
            "planning_feedback": planning_feedback_section(planning_feedback),
        },
    )


def plan_finalize_prompt(
    goal: str,
    root: Path,
    state: RunState,
    work: Path | None = None,
    *,
    same_session: bool,
    inspection_summary: str = "",
) -> str:
    context = _planning_context(goal, root, state, work)
    if same_session:
        return render_prompt_template(
            "plan_finalize_same_session.md",
            {
                "minimum_tasks": context["minimum_tasks"],
                "planning_mode": context["planning_mode"],
            },
        )

    return render_prompt_template(
        "plan_finalize.md",
        {
            **context,
            "source_instruction": (
                "This is a fresh no-tool fallback. Use only the supplied goal, progress, "
                "validator feedback, and inspection summary; do not "
                "inspect the repository."
            ),
            "inspection_summary": bounded_text(inspection_summary, 12000),
        },
    )


def plan_refine_prompt(
    goal: str,
    root: Path,
    state: RunState,
    tasks: Sequence[Task],
    work: Path | None = None,
    judge_issues: Sequence[str] = (),
    *,
    same_session: bool = True,
) -> str:
    feedback = "\n".join(f"- {item}" for item in judge_issues) or "- Re-check and correct the current plan."
    if same_session:
        return render_prompt_template("plan_refine.md", {"judge_feedback": feedback})
    return render_prompt_template(
        "plan_refine_full.md",
        {
            **_planning_context(goal, root, state, work),
            "tasks_json": json.dumps({"tasks": [task_spec(task) for task in tasks]}, ensure_ascii=False),
            "judge_feedback": "\nPlan judge issues that must all be resolved:\n" + feedback + "\n",
        },
    )

def plan_judge_prompt(
    goal: str,
    root: Path,
    state: RunState,
    tasks: Sequence[Task],
    work: Path | None = None,
    *,
    same_session: bool = True,
) -> str:
    if same_session:
        return render_prompt_template("plan_judge.md", {})
    return render_prompt_template(
        "plan_judge_full.md",
        {
            **_planning_context(goal, root, state, work),
            "tasks_json": json.dumps({"tasks": [task_spec(task) for task in tasks]}, ensure_ascii=False),
        },
    )

def structured_output_retry_prompt(error: str) -> str:
    """Short same-session correction for malformed structured model output."""
    return render_prompt_template(
        "structured_output_retry.md",
        {"error": error.strip()[-500:] or "invalid structured output"},
    )

def planning_feedback_section(feedback: str) -> str:
    text = feedback.strip()
    return f"\nPlanning feedback:\n{text}\n" if text else ""


def should_refresh_goal(state: RunState, has_session: bool) -> bool:
    """Full goal context is needed only when no usable session exists."""
    return not has_session


def _execution_feedback(
    state: RunState,
    strategy_note: str,
) -> str:
    """Return only information that was not already present in this session."""
    task = state.tasks[state.current]
    parts: list[str] = []
    if task.last_review and task.last_review.get("completed") is False:
        parts.append(
            "Latest review feedback:\n"
            + json.dumps(
                {
                    "reason": task.last_review.get("reason", ""),
                    "missing_items": task.last_review.get("missing_items", []),
                },
                ensure_ascii=False,
            )
        )
    if task.last_output and not (
        task.last_review and task.last_review.get("completed") is False
    ):
        parts.append("Latest execution diagnostic:\n" + task.last_output[-2000:])
    if strategy_note:
        parts.append("New recovery instruction:\n" + strategy_note)
    return "\n\n".join(parts) or "No new external feedback; continue from the existing session state."


def execution_prompt(
    state: RunState,
    root: Path,
    protected: Sequence[Path],
    strategy_note: str = "",
    validator_hint: str = "",
    include_goal: bool = True,
    rebuilt_session: bool = False,
) -> str:
    task = state.tasks[state.current]
    if not include_goal:
        template = "execution_continue.md" if task.attempts > 1 else "execution_next_todo.md"
        values = {"feedback": _execution_feedback(state, strategy_note)}
        if task.attempts <= 1:
            values["task_json"] = json.dumps(task_spec(task), ensure_ascii=False)
        return render_prompt_template(template, values)

    context = {
        "validator_feedback": format_validator_feedback(
            state.validator_output,
            2000,
        ),
        "global_constraints": shared_task_constraints(state),
    }
    strategy = f"\nRecovery instruction:\n{strategy_note}\n" if strategy_note else ""
    previous = (
        f"\nPrevious attempt output or diagnostic:\n{task.last_output[-2000:]}\n"
        if task.last_output
        else ""
    )
    review_feedback = ""
    if task.last_review and task.last_review.get("completed") is False:
        review_feedback = (
            "\nLatest review feedback:\n"
            + json.dumps(
                {
                    "reason": task.last_review.get("reason", ""),
                    "missing_items": task.last_review.get("missing_items", []),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    rebuilt_session_note = (
        "\nRebuilt session notice:\n"
        "This task is continuing in a rebuilt session. Project files may already "
        "contain changes from previous attempts. Before modifying or overwriting "
        "any existing file, read its current full content in this session.\n"
        if rebuilt_session
        else ""
    )
    validator_reference = (
        f"\nValidator reference:\n{validator_hint}\n"
        if validator_hint
        else ""
    )
    return render_prompt_template(
        "execution.md",
        {
            "rules": rules(root, protected),
            "goal": state.goal,
            "context_json": json.dumps(context, ensure_ascii=False),
            "validator_reference": validator_reference,
            "task_json": json.dumps(task_spec(task), ensure_ascii=False),
            "previous": previous,
            "review_feedback": review_feedback,
            "strategy": strategy,
            "rebuilt_session_note": rebuilt_session_note,
        },
    )


def review_prompt(
    state: RunState,
    root: Path,
    protected: Sequence[Path],
    output: str,
) -> str:
    task = state.tasks[state.current]
    feedback = format_validator_feedback(state.validator_output, 2000)
    validator_section = (
        f"\nLatest validator feedback to consider:\n{feedback}\n"
        if feedback
        else ""
    )
    return render_prompt_template(
        "review.md",
        {
            "always_instructions": _always_instructions(root),
            "global_constraints_json": json.dumps(
                shared_task_constraints(state), ensure_ascii=False
            ),
            "task_json": json.dumps(task_spec(task), ensure_ascii=False),
            "output": output[-3000:],
            "validator_section": validator_section,
        },
    )


def review_finalize_prompt(root: Path | None = None) -> str:
    prompt = render_prompt_template("review_finalize.md", {})
    return prompt + (_always_instructions(root) if root is not None else "")


def format_validator_feedback(feedback: str, limit: int = 2000) -> str:
    text = feedback.strip()
    if not text:
        return ""
    return render_prompt_template(
        "validator_feedback.md",
        {"feedback": bounded_text(text, limit)},
    )


def ai_validator_prompt(
    goal: str,
    root: Path,
    protected: Sequence[Path],
    custom: str = "",
    review_skipped: Sequence[dict[str, Any]] = (),
) -> str:
    notes = []
    if custom:
        notes.append(f"Additional validation instructions:\n{custom}")
    if review_skipped:
        notes.append(
            "The following TODOs were provisionally completed because AI Review "
            "was unavailable. Verify them independently and do not assume they passed Review:\n"
            + json.dumps(list(review_skipped), ensure_ascii=False)
        )
    extra = "\n" + "\n\n".join(notes) + "\n" if notes else ""
    return render_prompt_template(
        "ai_validator.md",
        {
            "rules": rules(root, protected),
            "goal": goal,
            "extra": extra,
        },
    )


__all__ = [
    "MAX_PROMPT_HISTORY_ITEMS",
    "PROMPT_DIR",
    "ai_validator_prompt",
    "bounded_text",
    "completed_titles",
    "execution_prompt",
    "format_validator_feedback",
    "plan_finalize_prompt",
    "plan_judge_prompt",
    "plan_refine_prompt",
    "plan_understand_prompt",
    "planning_feedback_section",
    "planning_rules",
    "render_prompt_template",
    "review_finalize_prompt",
    "review_prompt",
    "rules",
    "shared_task_constraints",
    "should_refresh_goal",
    "skipped_review_tasks",
    "structured_output_retry_prompt",
    "task_spec",
]
