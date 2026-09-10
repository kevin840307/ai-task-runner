from __future__ import annotations

import re
from pathlib import Path

PROJECT_WORKFLOW_ROOT = Path(".ai-task-runner") / "workflows"
_FOLDER_PART = re.compile(r"^[A-Za-z0-9_. -]+$")
_RESERVED_TECHNICAL_FOLDERS = {"__pycache__", "__pypackages__", "node_modules"}


def _normalize_package_folder(folder: str) -> str:
    raw = str(folder or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("Project Workflow folder must be a relative folder name")
    # One immediate folder == one owned Project Workflow package.  Keeping this
    # flat prevents support directories such as assets/workflow from becoming
    # accidental packages during discovery.
    lowered = raw.lower()
    if (lowered.startswith(".") or lowered in _RESERVED_TECHNICAL_FOLDERS or lowered.endswith(".egg-info")):
        raise ValueError("Project Workflow folder cannot be a reserved technical directory")
    if "/" in raw or raw in {".", ".."} or not _FOLDER_PART.fullmatch(raw):
        raise ValueError("Project Workflow folder must be one safe folder name")
    return raw


def project_workflow_root(project: Path) -> Path:
    return (project.resolve() / PROJECT_WORKFLOW_ROOT).resolve()


def project_package_root(project: Path, folder: str) -> Path:
    root = project_workflow_root(project)
    value = _normalize_package_folder(folder)
    target = (root / value).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Project Workflow package escapes its root") from exc
    return target


def project_package_workflow_dir(project: Path, folder: str) -> Path:
    return (project_package_root(project, folder) / "workflow").resolve()


def project_package_prompt_dir(project: Path, folder: str) -> Path:
    return (project_package_root(project, folder) / "prompts").resolve()


def iter_project_packages(project: Path):
    """Yield direct owned Project Workflow packages.

    Only ``<project>/.ai-task-runner/workflows/<folder>/workflow/`` is a
    discovery marker.  We intentionally do not recurse below ``<folder>`` so
    support content such as ``assets/workflow`` cannot appear as a second
    Workflow package.  ``.ai-task-runner.yaml`` remains policy/config only.
    """
    root = project_workflow_root(project)
    if not root.is_dir():
        return
    for package_root in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
        if package_root.is_symlink():
            continue
        try:
            folder = _normalize_package_folder(package_root.name)
            resolved_package = package_root.resolve()
            resolved_package.relative_to(root)
        except ValueError:
            continue
        workflow_link = package_root / "workflow"
        if workflow_link.is_symlink():
            continue
        workflow_dir = workflow_link.resolve()
        if not workflow_dir.is_dir():
            continue
        prompt_link = package_root / "prompts"
        if prompt_link.is_symlink():
            # Prompts are part of the same owned package; do not silently let a
            # package point its editable Prompt surface outside the Project.
            continue
        prompt_dir = prompt_link.resolve()
        yield folder, resolved_package, workflow_dir, prompt_dir


def project_package_for_asset(project: Path, path: Path) -> tuple[str, Path, Path, Path] | None:
    target = path.resolve()
    for row in iter_project_packages(project) or ():
        folder, package_root, workflow_dir, prompt_dir = row
        try:
            target.relative_to(package_root)
            return folder, package_root, workflow_dir, prompt_dir
        except ValueError:
            continue
    return None


def project_package_folders(project: Path) -> list[str]:
    return [row[0] for row in (iter_project_packages(project) or ())]
