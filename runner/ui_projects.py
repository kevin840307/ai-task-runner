"""Best-effort registration and shared locking for projects visible in the local UI."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from project_registry import project_file_lock, project_path_key


def normalize_project_name(value: str) -> str:
    """Normalize a display-only project name without changing project identity."""
    label = " ".join(str(value or "").split())
    if len(label) > 120:
        raise ValueError("project_name is too long")
    return label


def register_ui_project(
    project_root: str | Path,
    *,
    project_name: str = "",
    repo_root: Path | None = None,
) -> None:
    """Add a project root to the UI sidebar project list.

    CLI runs are allowed to work without the UI being open. Registration is
    therefore best-effort: project execution must not fail because the UI state
    file is unavailable or temporarily malformed. An explicit ``project_name``
    replaces the display name; otherwise an existing UI rename is preserved.
    """
    try:
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            return
        explicit_name = normalize_project_name(project_name)
        projects_file = (
            (repo_root or Path(__file__).resolve().parents[1])
            / "ui"
            / "data"
            / "projects.json"
        )
        projects_file.parent.mkdir(parents=True, exist_ok=True)
        with project_file_lock(projects_file):
            try:
                rows = json.loads(projects_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                rows = []
            if not isinstance(rows, list):
                rows = []

            key = project_path_key(root)
            existing_name = ""
            items = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                raw_path = str(row.get("path") or "").strip()
                if not raw_path:
                    continue
                if project_path_key(raw_path) == key:
                    existing_name = str(row.get("name") or "")
                    continue
                items.append(row)
            items.insert(0, {
                "name": explicit_name or existing_name or root.name or str(root),
                "path": str(root),
            })

            _atomic_write_projects(projects_file, items)
    except (OSError, ValueError):
        return



def _atomic_write_projects(projects_file: Path, items: list[dict]) -> None:
    tmp = projects_file.with_name(
        f"{projects_file.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, projects_file)


# Backward-compatible private alias used by older tests/callers.
_project_file_lock = project_file_lock

__all__ = [
    "normalize_project_name",
    "project_file_lock",
    "project_path_key",
    "register_ui_project",
]
