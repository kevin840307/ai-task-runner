"""Shared project rule-file generation for CLI AI backends."""
from __future__ import annotations

from pathlib import Path

from .policy import instruction_text
from ..plugins.registry import collect_plugin_instructions

RUNNER_RULE_MARKER = "# AI Task Runner Rules"
PROJECT_INSTRUCTIONS_START = "<!-- AI-TASK-RUNNER:PROJECT-INSTRUCTIONS -->"
PROJECT_INSTRUCTIONS_END = "<!-- /AI-TASK-RUNNER:PROJECT-INSTRUCTIONS -->"


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

    start = existing.find(PROJECT_INSTRUCTIONS_START)
    if start >= 0:
        end = existing.find(PROJECT_INSTRUCTIONS_END, start)
        if end >= 0:
            existing = (existing[:start] + existing[end + len(PROJECT_INSTRUCTIONS_END):]).rstrip()

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


__all__ = ["ensure_instruction_file"]
