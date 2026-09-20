"""Best-effort registration for projects visible in the local UI."""
from __future__ import annotations

import json
import os
from pathlib import Path


def register_ui_project(project_root: str | Path, *, repo_root: Path | None = None) -> None:
    """Add a project root to the UI sidebar project list.

    CLI runs are allowed to work without the UI being open. Registration is
    therefore best-effort: project execution must not fail because the UI state
    file is unavailable or temporarily malformed.
    """
    try:
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            return
        projects_file = (
            (repo_root or Path(__file__).resolve().parents[1])
            / "ui"
            / "data"
            / "projects.json"
        )
        projects_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            rows = json.loads(projects_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rows = []
        if not isinstance(rows, list):
            rows = []

        key = os.path.normcase(os.path.abspath(str(root)))
        items = [
            row
            for row in rows
            if isinstance(row, dict)
            and os.path.normcase(os.path.abspath(str(row.get("path") or ""))) != key
        ]
        items.insert(0, {"name": root.name or str(root), "path": str(root)})

        tmp = projects_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, projects_file)
    except OSError:
        return


__all__ = ["register_ui_project"]
