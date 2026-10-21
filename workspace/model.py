"""Workspace-only models. No Runner runtime state lives here."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class WorkspaceError(RuntimeError):
    """Fail-closed workspace/Git preparation error."""


class WorkspaceBlockedError(WorkspaceError):
    """Requested workspace policy is valid but cannot start right now."""


@dataclass(frozen=True)
class WorkspaceResolution:
    requested_mode: str
    effective_mode: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class PreparedWorkspace:
    task_id: str
    run_number: int
    requested_mode: str
    effective_mode: str
    target_branch: str
    target_head_sha_at_start: str
    task_branch: str
    task_base_sha: str
    repository_root: Path
    repository_identity: Path
    worktree_path: Path
    project_root: Path

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("repository_root", "repository_identity", "worktree_path", "project_root"):
            value[key] = str(value[key])
        return value
