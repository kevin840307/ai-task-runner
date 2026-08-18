"""Project safety and instruction policy loaded from the project root."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import RunnerError

POLICY_FILENAME = ".ai-task-runner.yaml"


def _load(root: Path) -> dict[str, Any]:
    policy = root / POLICY_FILENAME
    if not policy.is_file():
        return {}
    try:
        data: Any = yaml.safe_load(policy.read_text(encoding="utf-8")) or {}
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


def instructions(root: Path, name: str) -> str:
    """Return one optional user instruction block from project policy."""
    return (_load(root).get("instructions", {}).get(name, "") or "").strip()


def protected_paths(root: Path) -> list[Path]:
    """Load protected project-relative files/folders and protect the policy itself."""
    policy = root / POLICY_FILENAME
    if not policy.is_file():
        return []
    data = _load(root)
    values = data.get("protected_paths", [])
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
