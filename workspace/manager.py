"""Single resolver/prepare owner for Task execution workspaces."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from product_settings import AUTO_WORKSPACE_POLICIES

from .model import PreparedWorkspace, WorkspaceBlockedError, WorkspaceError, WorkspaceResolution
from .worktree import add_or_reuse_worktree, capture_target, repository_identity, repository_root

_REQUESTED_MODES = {"auto", "main", "worktree"}
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


def resolve_workspace_mode(
    requested_mode: str,
    *,
    auto_policy: str,
    main_running: bool,
    allow_concurrent_main_tasks: bool,
) -> WorkspaceResolution:
    requested = str(requested_mode or "auto").strip().lower()
    if requested not in _REQUESTED_MODES:
        raise WorkspaceError(f"Unsupported workspace mode: {requested}")
    policy = str(auto_policy or "").strip()
    if policy not in AUTO_WORKSPACE_POLICIES:
        raise WorkspaceError(f"Unsupported Auto workspace policy: {policy}")

    if requested == "worktree":
        return WorkspaceResolution(requested, "worktree", "explicit_worktree")

    if requested == "main":
        if main_running and not allow_concurrent_main_tasks:
            raise WorkspaceBlockedError("Main workspace is busy and concurrent Main tasks are disabled")
        return WorkspaceResolution(
            requested,
            "main",
            "explicit_main_concurrent" if main_running else "explicit_main",
        )

    if policy == "always-worktree":
        return WorkspaceResolution(requested, "worktree", "auto_always_worktree")
    if policy == "busy-worktree" and main_running:
        return WorkspaceResolution(requested, "worktree", "auto_busy_worktree")

    if main_running and not allow_concurrent_main_tasks:
        raise WorkspaceBlockedError("Main workspace is busy and concurrent Main tasks are disabled")
    return WorkspaceResolution(
        requested,
        "main",
        "auto_always_main_concurrent" if main_running else f"auto_{policy.replace('-', '_')}",
    )


def _run_identity(task_id: str, run_number: int) -> str:
    task = str(task_id or "").strip()
    if not _TASK_ID.fullmatch(task):
        raise WorkspaceError("Task id is invalid for workspace identity")
    try:
        run = int(run_number)
    except (TypeError, ValueError) as exc:
        raise WorkspaceError("Task run number must be a positive integer") from exc
    if run <= 0:
        raise WorkspaceError("Task run number must be a positive integer")
    return f"{task}-r{run}"


class WorkspaceManager:
    """Prepare isolated Task worktrees without importing Runner internals."""

    def __init__(self, *, worktree_root: Path | None = None) -> None:
        self._worktree_root = Path(worktree_root).expanduser().resolve() if worktree_root else None

    def prepare(
        self,
        project_root: Path,
        *,
        task_id: str,
        run_number: int,
        requested_mode: str,
        execution_settings: dict[str, Any],
        main_running: bool,
    ) -> PreparedWorkspace:
        execution = execution_settings if isinstance(execution_settings, dict) else {}
        resolution = resolve_workspace_mode(
            requested_mode,
            auto_policy=str(execution.get("auto_workspace_policy") or ""),
            main_running=bool(main_running),
            allow_concurrent_main_tasks=bool(execution.get("allow_concurrent_main_tasks", False)),
        )
        identity = _run_identity(task_id, run_number)
        project = Path(project_root).expanduser().resolve()
        repo = repository_root(project)
        target_branch, target_head = capture_target(repo)
        relative_project = project.relative_to(repo)
        root = self._worktree_root or (repo.parent / ".worktrees" / repo.name)
        worktree = (root / identity).resolve()
        task_branch = f"local/task/{identity}"

        add_or_reuse_worktree(
            repo,
            worktree,
            branch=task_branch,
            base_sha=target_head,
        )
        runner_project = (worktree / relative_project).resolve()
        if not runner_project.is_dir():
            raise WorkspaceError(f"Prepared Task project_root does not exist: {runner_project}")

        return PreparedWorkspace(
            task_id=str(task_id).strip(),
            run_number=int(run_number),
            requested_mode=resolution.requested_mode,
            effective_mode=resolution.effective_mode,
            target_branch=target_branch,
            target_head_sha_at_start=target_head,
            task_branch=task_branch,
            task_base_sha=target_head,
            repository_root=repo,
            repository_identity=repository_identity(repo),
            worktree_path=worktree,
            project_root=runner_project,
        )
