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
    source_project_root: Path
    worktree_path: Path
    project_root: Path

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in (
            "repository_root",
            "repository_identity",
            "source_project_root",
            "worktree_path",
            "project_root",
        ):
            value[key] = str(value[key])
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PreparedWorkspace":
        if not isinstance(value, dict):
            raise WorkspaceError("Workspace metadata must be an object")
        required = {
            "task_id",
            "run_number",
            "requested_mode",
            "effective_mode",
            "target_branch",
            "target_head_sha_at_start",
            "task_branch",
            "task_base_sha",
            "repository_root",
            "repository_identity",
            "source_project_root",
            "worktree_path",
            "project_root",
        }
        missing = sorted(required - set(value))
        if missing:
            raise WorkspaceError("Workspace metadata is missing: " + ", ".join(missing))
        try:
            run_number = int(value["run_number"])
        except (TypeError, ValueError) as exc:
            raise WorkspaceError("Workspace run_number is invalid") from exc
        return cls(
            task_id=str(value["task_id"]),
            run_number=run_number,
            requested_mode=str(value["requested_mode"]),
            effective_mode=str(value["effective_mode"]),
            target_branch=str(value["target_branch"]),
            target_head_sha_at_start=str(value["target_head_sha_at_start"]),
            task_branch=str(value["task_branch"]),
            task_base_sha=str(value["task_base_sha"]),
            repository_root=Path(str(value["repository_root"])).expanduser().resolve(),
            repository_identity=Path(str(value["repository_identity"])).expanduser().resolve(),
            source_project_root=Path(str(value["source_project_root"])).expanduser().resolve(),
            worktree_path=Path(str(value["worktree_path"])).expanduser().resolve(),
            project_root=Path(str(value["project_root"])).expanduser().resolve(),
        )


@dataclass(frozen=True)
class WorkspaceCleanupResult:
    status: str
    branch: str
    worktree_path: Path
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["worktree_path"] = str(self.worktree_path)
        return value


@dataclass(frozen=True)
class WorkspaceSnapshot:
    task_snapshot_sha: str
    no_changes: bool
    created_commit: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PublishResult:
    status: str
    branch: str
    sha: str
    remote: str = "origin"
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MergeResult:
    status: str
    target_head_sha: str = ""
    merged_target_head_sha: str = ""
    target_worktree: Path | None = None
    validation_required: bool = False
    verdict: str = ""
    real_merge_failure: bool = False
    conflict_files: tuple[str, ...] = ()
    merge_queue_seq: int = 0
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.target_worktree is not None:
            value["target_worktree"] = str(self.target_worktree)
        return value
