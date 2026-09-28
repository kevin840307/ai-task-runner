from __future__ import annotations

from pathlib import Path

PROJECT_WORKFLOW_ROOT = Path(".ai-task-runner") / "workflows"


def project_workflow_root(project: Path) -> Path:
    """Return the editable Project-local Workflow/Prompt asset directory."""
    return (project.resolve() / PROJECT_WORKFLOW_ROOT).resolve()


__all__ = ["PROJECT_WORKFLOW_ROOT", "project_workflow_root"]
