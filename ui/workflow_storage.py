from __future__ import annotations

from pathlib import Path

PROJECT_ASSET_ROOT = Path(".ai-task-runner") / "assets"


def project_asset_root(project: Path, kind: str) -> Path:
    """Return one Project-local editable asset root."""
    name = "workflows" if kind == "workflow" else "prompts" if kind == "prompt" else ""
    if not name:
        raise ValueError("asset kind must be workflow or prompt")
    return (project.resolve() / PROJECT_ASSET_ROOT / name).resolve()


__all__ = ["PROJECT_ASSET_ROOT", "project_asset_root"]
