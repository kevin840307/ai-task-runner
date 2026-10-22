"""Backend bridge from Task orchestration to stable Runner public APIs.

UI owns presentation and Task lifecycle state. This module is the thin backend
boundary that may import Runner public APIs without teaching UI or workspace/
about Runner internals.
"""
from __future__ import annotations

from pathlib import Path

from runner.api import RunRequest, validate_only


def validate_merge(
    project: Path,
    goal: str,
    *,
    backend: str = "",
    validator: str = "",
    workflow: str = "",
) -> str:
    """Run validation-only against a prepared merge candidate."""
    result = validate_only(
        RunRequest(
            goal=goal or "Merge validation",
            project_root=str(Path(project).expanduser().resolve()),
            validator=validator or None,
            workflow_file=workflow or None,
            backend=backend or "qwen",
            auto_register_ui_project=False,
            human_output=False,
        )
    )
    return result.verdict
