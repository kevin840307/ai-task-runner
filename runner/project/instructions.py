"""Shared project rule-file generation for CLI AI backends."""
from __future__ import annotations

from pathlib import Path

from .policy import instruction_text
from ..plugins.registry import collect_plugin_instructions

RUNNER_RULE_MARKER = "# AI Task Runner Rules"
PROJECT_INSTRUCTIONS_START = "<!-- AI-TASK-RUNNER:PROJECT-INSTRUCTIONS -->"
PROJECT_INSTRUCTIONS_END = "<!-- /AI-TASK-RUNNER:PROJECT-INSTRUCTIONS -->"


def _without_managed_block(text: str, start_marker: str, end_marker: str) -> str:
    """Remove one Runner-owned block while preserving user-authored content."""
    start = text.find(start_marker)
    if start < 0:
        return text.rstrip()
    end = text.find(end_marker, start)
    return (text[:start] + text[end + len(end_marker):]).rstrip() if end >= 0 else text.rstrip()


def ensure_instruction_file(root: Path, filename: str) -> Path:
    path = root / filename
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if RUNNER_RULE_MARKER not in existing:
        existing = existing.rstrip() + f"""

{RUNNER_RULE_MARKER}
- You may read files outside this project when needed.
- You may write, create, rename, or delete files only under: {root}
- Never modify runner state directly.
- Python owns task order and completion state.
- Execute only the current task supplied by the runner.
{collect_plugin_instructions(root)}
- Complete the task with the smallest clean change possible; avoid unnecessary code, files, abstractions, dependencies, refactoring, or unrelated modifications.
- Never ask the user questions. Inspect the project, make the safest reasonable assumption, and continue.
"""

    existing = _without_managed_block(
        existing, PROJECT_INSTRUCTIONS_START, PROJECT_INSTRUCTIONS_END
    )

    project = instruction_text(root, "project")
    if project:
        existing += f"""

{PROJECT_INSTRUCTIONS_START}
# User Project Instructions
{project}
{PROJECT_INSTRUCTIONS_END}
"""
    path.write_text(existing.rstrip() + "\n", encoding="utf-8")
    return path

GOAL_REFERENCE_START = "<!-- AI-TASK-RUNNER:GOAL-REFERENCE -->"
GOAL_REFERENCE_END = "<!-- /AI-TASK-RUNNER:GOAL-REFERENCE -->"


def update_goal_reference(root: Path, filename: str, goal_file: str | None) -> Path:
    """Maintain one replaceable goal-file reference in a backend rule file."""
    path = ensure_instruction_file(root, filename)
    text = path.read_text(encoding="utf-8")
    text = _without_managed_block(text, GOAL_REFERENCE_START, GOAL_REFERENCE_END)
    if goal_file:
        reference = Path(goal_file).expanduser().resolve().as_posix()
        text += f"""

{GOAL_REFERENCE_START}
Original requirement file: {reference}

If the original requirements are unclear, missing from context, or appear to
conflict with the current task or feedback, reread this file before continuing.
The original requirements remain authoritative; review or validator feedback
does not replace or narrow them.
{GOAL_REFERENCE_END}
"""
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


__all__ = ["ensure_instruction_file", "update_goal_reference"]
