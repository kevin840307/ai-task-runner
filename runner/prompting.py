"""Prompt template loading and prompt builders."""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from string import Template as PromptTemplate
from typing import Any, Sequence

from .errors import RunnerError
from .models import RunState, Task


PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
MAX_PROMPT_HISTORY_ITEMS = 20


PROJECT_OUTLINE_EXCLUDE_DIRS = frozenset({
    ".git",
    ".ai-task-runner",
    ".idea",
    ".qwen",
    ".venv",
    ".vs",
    "__pycache__",
    "bin",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "obj",
    "target",
})


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


def project_outline(root: Path, limit: int = 120) -> str:
    """Return a compact read-only project outline for planning prompts."""
    entries: list[str] = []
    queue = deque([root])
    while queue and len(entries) < limit:
        base = queue.popleft()
        try:
            children = sorted(base.iterdir(), key=lambda path: (path.is_file(), path.name.lower()))
        except OSError:
            continue
        directories = [
            path for path in children
            if path.is_dir()
            and path.name not in PROJECT_OUTLINE_EXCLUDE_DIRS
            and not path.name.startswith(".")
        ]
        files = [
            path for path in children
            if path.is_file() and not path.name.startswith(".")
        ]
        for path in [*directories, *files]:
            relative = path.relative_to(root).as_posix()
            entries.append(relative + ("/" if path.is_dir() else ""))
            if len(entries) >= limit:
                entries.append("...")
                return "\n".join(entries)
        queue.extend(directories)
    return "\n".join(entries) if entries else "(no project files)"


def render_prompt_template(name: str, values: dict[str, Any]) -> str:
    path = PROMPT_DIR / name
    try:
        template = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RunnerError(f"missing prompt template: {path}") from error
    return PromptTemplate(template).safe_substitute(
        {key: str(value) for key, value in values.items()}
    )


def rules(root: Path, protected: Sequence[Path]) -> str:
    protected_names = "\n".join(f"- {path}" for path in protected)
    return render_prompt_template(
        "rules.md",
        {"root": root, "protected_names": protected_names},
    )


def planning_rules(work: Path) -> str:
    return render_prompt_template("planning_rules.md", {"work": work})


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
            "review_error_attempts": task.review_error_attempts,
        }
        for task in state.tasks
        if task.review_skipped
    ][-MAX_PROMPT_HISTORY_ITEMS:]


def plan_prompt(
    goal: str,
    root: Path,
    state: RunState,
    protected: Sequence[Path],
    work: Path | None = None,
    planning_feedback: str = "",
) -> str:
    progress = {
        "cycle": state.cycle,
        "validator_feedback": state.validator_output[-8000:],
        "completed_tasks": completed_titles(state),
        "review_skipped_tasks": skipped_review_tasks(state),
    }
    work_dir = work or root / ".ai-task-runner"
    return render_prompt_template(
        "plan.md",
        {
            "planning_rules": planning_rules(work_dir),
            "goal": goal,
            "root": root,
            "outline": project_outline(root),
            "progress_json": json.dumps(progress, ensure_ascii=False),
            "work_dir": work_dir,
            "planning_feedback": planning_feedback_section(planning_feedback),
            "minimum_tasks": 6 if state.cycle == 1 else 1,
            "planning_mode": "initial" if state.cycle == 1 else "repair",
        },
    )


def plan_refine_prompt(
    goal: str,
    root: Path,
    state: RunState,
    tasks: Sequence[Task],
    work: Path | None = None,
    judge_issues: Sequence[str] = (),
) -> str:
    progress = {
        "cycle": state.cycle,
        "validator_feedback": state.validator_output[-8000:],
        "completed_tasks": completed_titles(state),
        "review_skipped_tasks": skipped_review_tasks(state),
    }
    work_dir = work or root / ".ai-task-runner"
    return render_prompt_template(
        "plan_refine.md",
        {
            "planning_rules": planning_rules(work_dir),
            "goal": goal,
            "root": root,
            "outline": project_outline(root),
            "progress_json": json.dumps(progress, ensure_ascii=False),
            "tasks_json": json.dumps(
                {"tasks": [task_spec(task) for task in tasks]},
                ensure_ascii=False,
            ),
            "minimum_tasks": 6 if state.cycle == 1 else 1,
            "planning_mode": "initial" if state.cycle == 1 else "repair",
            "judge_feedback": (
                "\nPlan judge issues that must all be resolved:\n"
                + "\n".join(f"- {item}" for item in judge_issues)
                + "\n"
                if judge_issues
                else ""
            ),
        },
    )


def plan_judge_prompt(
    goal: str,
    root: Path,
    state: RunState,
    tasks: Sequence[Task],
    work: Path | None = None,
) -> str:
    progress = {
        "cycle": state.cycle,
        "validator_feedback": state.validator_output[-8000:],
        "completed_tasks": completed_titles(state),
        "review_skipped_tasks": skipped_review_tasks(state),
    }
    work_dir = work or root / ".ai-task-runner"
    return render_prompt_template(
        "plan_judge.md",
        {
            "planning_rules": planning_rules(work_dir),
            "goal": goal,
            "root": root,
            "outline": project_outline(root),
            "progress_json": json.dumps(progress, ensure_ascii=False),
            "tasks_json": json.dumps(
                {"tasks": [task_spec(task) for task in tasks]},
                ensure_ascii=False,
            ),
            "minimum_tasks": 6 if state.cycle == 1 else 1,
            "planning_mode": "initial" if state.cycle == 1 else "repair",
        },
    )


def planning_feedback_section(feedback: str) -> str:
    text = feedback.strip()
    return f"\nPlanning feedback:\n{text}\n" if text else ""


def should_refresh_goal(state: RunState, has_session: bool) -> bool:
    """Identify executions that need explicit new-session context."""
    task = state.tasks[state.current]
    return not has_session or (
        state.cycle > 1
        and task.attempts == 1
        and task.id == f"c{state.cycle:02d}-t001"
    )


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
    context = {
        "validator_feedback": format_validator_feedback(
            state.validator_output,
            2000,
        ),
        "global_constraints": shared_task_constraints(state),
        "execution_scope": (
            "Global constraints are compatibility and safety boundaries only. "
            "The current TODO is the only executable work item."
        ),
        "session_context": (
            "New execution session. Treat the current TODO as self-contained; inspect only "
            "the project files directly needed to complete its deliverable."
            if include_goal
            else
            "Continue the current TODO using the existing session context."
        ),
    }
    strategy = f"\nRecovery instruction:\n{strategy_note}\n" if strategy_note else ""
    previous = (
        f"\nPrevious attempt output or diagnostic:\n{task.last_output[-2000:]}\n"
        if task.last_output
        else ""
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
            "context_json": json.dumps(context, ensure_ascii=False),
            "validator_reference": validator_reference,
            "task_json": json.dumps(task_spec(task), ensure_ascii=False),
            "previous": previous,
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
            "rules": rules(root, protected),
            "global_constraints_json": json.dumps(
                shared_task_constraints(state), ensure_ascii=False
            ),
            "task_json": json.dumps(task_spec(task), ensure_ascii=False),
            "changed_files_json": json.dumps(task.changed_files, ensure_ascii=False),
            "output": output[-3000:],
            "validator_section": validator_section,
        },
    )


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
