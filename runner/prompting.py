"""Prompt template loading and prompt builders."""
from __future__ import annotations

import json
import os
from pathlib import Path
from string import Template as PromptTemplate
from typing import Any, Sequence

from .errors import RunnerError
from .models import RunState, Task


PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
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
    for current, directories, files in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = [
            name for name in directories
            if name not in PROJECT_OUTLINE_EXCLUDE_DIRS and not name.startswith(".")
        ]
        for name in sorted(files):
            if name.startswith("."):
                continue
            relative = (base / name).relative_to(root).as_posix()
            entries.append(relative)
            if len(entries) >= limit:
                entries.append("...")
                return "\n".join(entries)
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
        "acceptance_criteria": task.acceptance_criteria,
    }


def completed_titles(state: RunState) -> list[str]:
    return [task.title for task in state.tasks if task.status == "completed"]


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
        },
    )


def planning_feedback_section(feedback: str) -> str:
    text = feedback.strip()
    return f"\nPlanning feedback:\n{text}\n" if text else ""


def execution_prompt(
    state: RunState,
    root: Path,
    protected: Sequence[Path],
    strategy_note: str = "",
    validator_hint: str = "",
) -> str:
    task = state.tasks[state.current]
    context = {
        "goal": state.goal,
        "completed_tasks": completed_titles(state),
        "validator_feedback": format_validator_feedback(
            state.validator_output,
            2000,
        ),
    }
    strategy = f"\nRecovery instruction:\n{strategy_note}\n" if strategy_note else ""
    previous = (
        f"\nPrevious attempt output or diagnostic:\n{task.last_output[-2000:]}\n"
        if task.last_output
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
            "task_json": json.dumps(task_spec(task), ensure_ascii=False),
            "output": output[-5000:],
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
) -> str:
    extra = (
        f"\nAdditional validation instructions:\n{custom}\n"
        if custom
        else ""
    )
    return render_prompt_template(
        "ai_validator.md",
        {
            "rules": rules(root, protected),
            "goal": goal,
            "extra": extra,
        },
    )
