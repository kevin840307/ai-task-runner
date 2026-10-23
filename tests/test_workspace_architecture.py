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

def test_ui_never_executes_git_and_remote_push_is_confined_to_publish_adapter() -> None:
    ui_git_callers: set[str] = set()
    push_callers: set[str] = set()

    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if "tests" in relative.parts or "feature" in relative.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name != "git":
                continue
            if relative.parts and relative.parts[0] == "ui":
                ui_git_callers.add(relative.as_posix())
            if (
                len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "push"
            ):
                push_callers.add(relative.as_posix())

    assert ui_git_callers == set()
    assert push_callers == {"workspace/publish.py"}

