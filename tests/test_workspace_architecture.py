from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_runner_and_workspace_remain_independent_packages() -> None:
    workspace_imports: set[str] = set()
    for path in (ROOT / "workspace").glob("*.py"):
        workspace_imports |= _import_roots(path)
    assert "runner" not in workspace_imports
    assert "ui" not in workspace_imports

    runner_importers = []
    for path in (ROOT / "runner").rglob("*.py"):
        if "workspace" in _import_roots(path):
            runner_importers.append(path.relative_to(ROOT).as_posix())
    assert runner_importers == []
