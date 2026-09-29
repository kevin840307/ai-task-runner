"""Workspace files, policy, and managed AI instruction files."""
from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from .errors import RunnerError
from .plugins.registry import collect_plugin_instructions
from .utils import copy_path, digest, io_path, remove_path

POLICY_FILENAME = ".ai-task-runner.yaml"
RUNNER_RULE_MARKER = "# AI Task Runner Rules"
PROJECT_INSTRUCTIONS_START = "<!-- AI-TASK-RUNNER:PROJECT-INSTRUCTIONS -->"
PROJECT_INSTRUCTIONS_END = "<!-- /AI-TASK-RUNNER:PROJECT-INSTRUCTIONS -->"
GOAL_REFERENCE_START = "<!-- AI-TASK-RUNNER:GOAL-REFERENCE -->"
GOAL_REFERENCE_END = "<!-- /AI-TASK-RUNNER:GOAL-REFERENCE -->"

TECHNICAL_EXCLUDE_DIRS = frozenset({
    ".ai-task-runner", ".git", ".gradle", ".idea", ".mypy_cache", ".nox",
    ".pytest_cache", ".ruff_cache", ".tox", ".venv", ".vs", ".vscode",
    "__pycache__", "bin", "build", "coverage", "dist", "htmlcov",
    "node_modules", "obj", "target", "testresults",
})
TECHNICAL_EXCLUDE_FILES = frozenset({".coverage", ".ds_store", "thumbs.db"})
TECHNICAL_EXCLUDE_SUFFIXES = frozenset({".pyc", ".pyo"})
READONLY_EXCLUDE_DIRS = TECHNICAL_EXCLUDE_DIRS
STALE_TEMP_SECONDS = 7 * 24 * 60 * 60
STALE_TEMP_PREFIXES = (
    "ai-task-runner-readonly-*",
    "ai-task-runner-readonly-cache-*",
    "ai-task-runner-protect-*",
)


def _key(value: str) -> str:
    return value.casefold()


def is_technical_artifact(path: Path | str, *, is_dir: bool | None = None) -> bool:
    value = Path(path)
    parts = value.parts
    if not parts:
        return False
    ancestor_parts = parts if is_dir else parts[:-1]
    if any(_key(part) in TECHNICAL_EXCLUDE_DIRS for part in ancestor_parts):
        return True
    name = _key(parts[-1])
    if is_dir is True:
        return name in TECHNICAL_EXCLUDE_DIRS
    if is_dir is False:
        return (
            name in TECHNICAL_EXCLUDE_FILES
            or Path(name).suffix in TECHNICAL_EXCLUDE_SUFFIXES
        )
    return (
        name in TECHNICAL_EXCLUDE_DIRS
        or name in TECHNICAL_EXCLUDE_FILES
        or Path(name).suffix in TECHNICAL_EXCLUDE_SUFFIXES
    )


def excluded_dirs(root: Path, work: Path) -> set[str]:
    excluded = set(TECHNICAL_EXCLUDE_DIRS)
    if work.is_relative_to(root):
        excluded.add(_key(work.relative_to(root).parts[0]))
    return excluded


def tree_manifest(root: Path, excluded: set[str]) -> dict[str, tuple[str, str | None]]:
    result: dict[str, tuple[str, str | None]] = {}
    excluded_keys = {_key(value) for value in excluded}
    walk_root = io_path(root)
    for current, directories, files in os.walk(walk_root, followlinks=False):
        base = Path(current)
        directories[:] = [
            name for name in directories if _key(name) not in excluded_keys
        ]
        for name in list(directories):
            path = base / name
            relative = path.relative_to(walk_root).as_posix()
            if path.is_symlink():
                result[relative] = ("link", os.readlink(path))
                directories.remove(name)
            else:
                result[relative] = ("dir", "")
        for name in files:
            if is_technical_artifact(Path(name), is_dir=False):
                continue
            path = base / name
            relative = path.relative_to(walk_root).as_posix()
            result[relative] = (
                "link" if path.is_symlink() else "file",
                os.readlink(path) if path.is_symlink() else digest(path),
            )
    return result


def project_manifest(root: Path, work: Path) -> dict[str, tuple[str, str | None]]:
    return tree_manifest(root, excluded_dirs(root, work))


def changed_project_files(
    root: Path,
    work: Path,
    before: dict[str, tuple[str, str | None]],
) -> list[str]:
    after = project_manifest(root, work)
    changed: list[str] = []
    for path in set(before) | set(after):
        if before.get(path) == after.get(path):
            continue
        if (
            before.get(path, (None, None))[0] == "dir"
            or after.get(path, (None, None))[0] == "dir"
        ):
            continue
        changed.append(path)
    return sorted(changed)


def restore_project_changes(root: Path, backup: Path, changed: Sequence[str]) -> None:
    paths = [Path(relative) for relative in changed]
    for relative in sorted(paths, key=lambda value: len(value.parts), reverse=True):
        remove_path(root / relative)
    for relative in sorted(paths, key=lambda value: len(value.parts)):
        source, target = backup / relative, root / relative
        target_io, source_io = io_path(target), io_path(source)
        if not (target_io.exists() or target_io.is_symlink()) and (
            source_io.exists() or source_io.is_symlink()
        ):
            copy_path(source, target)


def cleanup_stale_artifacts(
    work: Path,
    temp_root: Path | None = None,
    older_than: float = STALE_TEMP_SECONDS,
) -> None:
    work.mkdir(parents=True, exist_ok=True)
    for path in work.glob("*.tmp"):
        remove_path(path)
    cutoff = time.time() - older_than
    root = temp_root or Path(tempfile.gettempdir())
    for pattern in STALE_TEMP_PREFIXES:
        for path in root.glob(pattern):
            try:
                if path.stat().st_mtime < cutoff:
                    remove_path(path)
            except OSError:
                continue


def _load_policy(root: Path) -> dict[str, Any]:
    policy = root / POLICY_FILENAME
    if not policy.is_file():
        return {}
    try:
        data: Any = yaml.safe_load(io_path(policy).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise RunnerError(f"invalid {POLICY_FILENAME}: {error}") from error
    if not isinstance(data, dict):
        raise RunnerError(f"invalid {POLICY_FILENAME}: root must be a mapping")
    unknown = sorted(set(data) - {"protected_paths", "instructions"})
    if unknown:
        raise RunnerError(
            f"invalid {POLICY_FILENAME}: unknown keys: " + ", ".join(unknown)
        )
    instructions = data.get("instructions", {}) or {}
    if not isinstance(instructions, dict):
        raise RunnerError(f"invalid {POLICY_FILENAME}: instructions must be a mapping")
    unknown = sorted(set(instructions) - {"always", "project"})
    if unknown:
        raise RunnerError(
            f"invalid {POLICY_FILENAME}: unknown instruction keys: " + ", ".join(unknown)
        )
    if any(
        key in instructions and not isinstance(instructions[key], str)
        for key in ("always", "project")
    ):
        raise RunnerError(
            f"invalid {POLICY_FILENAME}: instruction values must be strings"
        )
    return data


def instruction_text(root: Path, name: str) -> str:
    return (_load_policy(root).get("instructions", {}).get(name, "") or "").strip()


def protected_paths(root: Path) -> list[Path]:
    policy = root / POLICY_FILENAME
    if not policy.is_file():
        return []
    values = _load_policy(root).get("protected_paths", [])
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise RunnerError(
            f"invalid {POLICY_FILENAME}: protected_paths must be a list of paths"
        )
    project = root.resolve()
    result = [policy.resolve()]
    for value in values:
        relative = Path(value.strip())
        if relative.is_absolute() or ".." in relative.parts:
            raise RunnerError(
                f"invalid {POLICY_FILENAME}: protected path must stay inside project_root: {value}"
            )
        path = (project / relative).resolve()
        if not path.is_relative_to(project):
            raise RunnerError(
                f"invalid {POLICY_FILENAME}: protected path must stay inside project_root: {value}"
            )
        result.append(path)
    return list(dict.fromkeys(result))


def _without_managed_block(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        return text.rstrip()
    end = text.find(end_marker, start)
    return (
        (text[:start] + text[end + len(end_marker):]).rstrip()
        if end >= 0
        else text.rstrip()
    )


def ensure_instruction_file(root: Path, filename: str) -> Path:
    path = root / filename
    existing = io_path(path).read_text(encoding="utf-8") if io_path(path).exists() else ""
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
    io_path(path).write_text(existing.rstrip() + "\n", encoding="utf-8")
    return path


def update_goal_reference(root: Path, filename: str, goal_file: str | None) -> Path:
    path = ensure_instruction_file(root, filename)
    text = io_path(path).read_text(encoding="utf-8")
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
    io_path(path).write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


__all__ = [
    "POLICY_FILENAME",
    "READONLY_EXCLUDE_DIRS",
    "STALE_TEMP_PREFIXES",
    "STALE_TEMP_SECONDS",
    "TECHNICAL_EXCLUDE_DIRS",
    "TECHNICAL_EXCLUDE_FILES",
    "TECHNICAL_EXCLUDE_SUFFIXES",
    "changed_project_files",
    "cleanup_stale_artifacts",
    "ensure_instruction_file",
    "excluded_dirs",
    "instruction_text",
    "is_technical_artifact",
    "project_manifest",
    "protected_paths",
    "restore_project_changes",
    "tree_manifest",
    "update_goal_reference",
]
