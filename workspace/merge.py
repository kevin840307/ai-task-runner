"""Direct local Task delivery transaction. No Runner imports live here."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from .merge_queue import MergeQueue
from .model import MergeResult, PreparedWorkspace, WorkspaceError, WorkspaceSnapshot
from .worktree import (
    active_git_operations,
    branch_head,
    git,
    is_ancestor,
    repository_git_lock,
    repository_identity,
    target_branch_git_lock,
    verify_worktree,
)

ValidationCallback = Callable[[Path], str]
_VALIDATION_RESULTS = {"PASS", "SOURCE_FAIL", "TECHNICAL_ERROR"}


def _worktrees(repo: Path) -> list[dict[str, object]]:
    raw = git(repo, "worktree", "list", "--porcelain").stdout
    rows: list[dict[str, object]] = []
    current: dict[str, object] = {}
    for line in [*raw.splitlines(), ""]:
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = Path(value).resolve()
        elif key == "HEAD":
            current["head"] = value.strip()
        elif key == "branch":
            current["branch"] = value.removeprefix("refs/heads/").strip()
        elif key == "detached":
            current["detached"] = True
    return rows


def _delivery_path(prepared: PreparedWorkspace) -> Path:
    key = hashlib.sha256(prepared.target_branch.encode("utf-8")).hexdigest()[:16]
    return (prepared.worktree_path.parent / "_delivery" / key).resolve()


def _target_project(prepared: PreparedWorkspace, target_worktree: Path) -> Path:
    try:
        relative = prepared.source_project_root.resolve().relative_to(
            prepared.repository_root.resolve()
        )
    except ValueError as exc:
        raise WorkspaceError("Captured Project is outside repository root") from exc
    project = (target_worktree.resolve() / relative).resolve()
    if not project.is_dir():
        raise WorkspaceError(f"Target Project path is missing: {project}")
    return project


def _find_target_worktree(
    prepared: PreparedWorkspace,
) -> tuple[Path | None, bool, MergeResult | None]:
    repo = prepared.repository_root.resolve()
    branch = prepared.target_branch
    target_sha = branch_head(repo, branch)
    if not target_sha:
        return None, False, MergeResult(status="waiting_target_branch")

    records = [row for row in _worktrees(repo) if row.get("branch") == branch]
    managed = _delivery_path(prepared)
    if len(records) > 1:
        return None, False, MergeResult(
            status="waiting_target_workspace",
            target_head_sha=target_sha,
            detail="Captured target branch is checked out in multiple worktrees",
        )
    if records:
        path = Path(records[0]["path"]).resolve()
        if path == prepared.repository_root.resolve():
            return path, False, None
        if path == managed:
            return path, True, None
        return None, False, MergeResult(
            status="waiting_target_workspace",
            target_head_sha=target_sha,
            target_worktree=path,
            detail="Captured target branch is checked out in an unmanaged worktree",
        )

    with repository_git_lock(repo):
        records = [row for row in _worktrees(repo) if row.get("branch") == branch]
        if len(records) > 1:
            return None, False, MergeResult(
                status="waiting_target_workspace",
                target_head_sha=branch_head(repo, branch),
                detail="Captured target branch became checked out in multiple worktrees",
            )
        if records:
            path = Path(records[0]["path"]).resolve()
            if path == prepared.repository_root.resolve():
                return path, False, None
            if path == managed:
                return path, True, None
            return None, False, MergeResult(
                status="waiting_target_workspace",
                target_head_sha=branch_head(repo, branch),
                target_worktree=path,
                detail="Captured target branch became checked out in an unmanaged worktree",
            )
        if managed.exists():
            raise WorkspaceError(
                f"Managed delivery path exists but is not a registered worktree: {managed}"
            )
        managed.parent.mkdir(parents=True, exist_ok=True)
        git(repo, "worktree", "add", str(managed), branch)
    return managed, True, None


def _cleanup_delivery(repo: Path, path: Path, branch: str) -> str:
    try:
        with repository_git_lock(repo):
            if not path.exists():
                return ""
            current = git(path, "branch", "--show-current").stdout.strip()
            if current != branch:
                return f"managed delivery branch changed to {current or 'detached/unknown'}"
            if active_git_operations(path):
                return "managed delivery worktree still has an active Git operation"
            if git(path, "status", "--porcelain=v1", "-z").stdout:
                return "managed delivery worktree is not clean"
            git(repo, "worktree", "remove", str(path))
        return ""
    except WorkspaceError as exc:
        return str(exc)


def _target_has_source_changes(prepared: PreparedWorkspace, target: Path) -> bool:
    """Ignore only AI Task Runner runtime state; keep real Project metadata dirty."""
    project = _target_project(prepared, target)
    runtime_state = (project / ".ai-task-runner").relative_to(target).as_posix()
    result = git(
        target,
        "status",
        "--porcelain=v1",
        "-z",
        "--",
        ".",
        f":(exclude){runtime_state}",
        f":(exclude){runtime_state}/**",
    )
    return bool(result.stdout)


def _abort_owned_merge(target: Path, source_sha: str) -> None:
    merge_head = git(target, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    if merge_head.returncode != 0:
        return
    if merge_head.stdout.strip() != source_sha:
        raise WorkspaceError("Target worktree MERGE_HEAD no longer belongs to this Task merge")
    result = git(target, "merge", "--abort", check=False)
    if result.returncode != 0:
        raise WorkspaceError(
            "Could not abort Task merge: " + (result.stderr or result.stdout or "").strip()
        )


def _transaction_owned(
    prepared: PreparedWorkspace,
    target: Path,
    *,
    target_head: str,
    source_sha: str,
    expected_index_tree: str,
) -> bool:
    branch = git(target, "branch", "--show-current").stdout.strip()
    head = git(target, "rev-parse", "HEAD").stdout.strip()
    merge_head = git(target, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    operations = active_git_operations(target)
    index_tree = git(target, "write-tree", check=False)
    working_diff = git(target, "diff", "--quiet", check=False)
    return (
        branch == prepared.target_branch
        and head == target_head
        and merge_head.returncode == 0
        and merge_head.stdout.strip() == source_sha
        and operations == ("MERGE_HEAD",)
        and branch_head(prepared.repository_root, prepared.task_branch) == source_sha
        and index_tree.returncode == 0
        and index_tree.stdout.strip() == expected_index_tree
        and working_diff.returncode == 0
    )


class MergeManager:
    """One direct merge transaction owner; orchestration/recovery stays outside."""

    def release_merge_slot(
        self,
        prepared: PreparedWorkspace,
        snapshot: WorkspaceSnapshot,
    ) -> bool:
        """Release a retained queue head after the caller durably chooses fallback."""
        repo = prepared.repository_root.resolve()
        if repository_identity(repo) != prepared.repository_identity.resolve():
            raise WorkspaceError("Workspace repository identity changed before queue release")
        verify_worktree(
            repo,
            prepared.worktree_path,
            expected_branch=prepared.task_branch,
            expected_base_sha=prepared.task_base_sha,
        )
        if branch_head(repo, prepared.task_branch) != snapshot.task_snapshot_sha:
            raise WorkspaceError("Task snapshot no longer matches Task branch HEAD")
        return MergeQueue(repo, prepared.target_branch).release_head(
            task_id=prepared.task_id,
            run_number=prepared.run_number,
        )

    def merge(
        self,
        prepared: PreparedWorkspace,
        snapshot: WorkspaceSnapshot,
        *,
        validate: ValidationCallback | None = None,
        commit_message: str = "",
    ) -> MergeResult:
        repo = prepared.repository_root.resolve()
        if repository_identity(repo) != prepared.repository_identity.resolve():
            raise WorkspaceError("Workspace repository identity changed before merge")
        verify_worktree(
            repo,
            prepared.worktree_path,
            expected_branch=prepared.task_branch,
            expected_base_sha=prepared.task_base_sha,
        )
        source_sha = snapshot.task_snapshot_sha
        if branch_head(repo, prepared.task_branch) != source_sha:
            raise WorkspaceError("Task snapshot no longer matches Task branch HEAD")
        if not is_ancestor(repo, prepared.task_base_sha, source_sha):
            raise WorkspaceError("Task snapshot no longer descends from Task base")
        if snapshot.no_changes:
            target_head = branch_head(repo, prepared.target_branch)
            managed = _delivery_path(prepared)
            cleanup = _cleanup_delivery(repo, managed, prepared.target_branch) if managed.exists() else ""
            return MergeResult(
                status="no_changes",
                target_head_sha=target_head,
                merged_target_head_sha=target_head,
                detail=cleanup,
            )

        queue = MergeQueue(repo, prepared.target_branch)
        queue_entry, is_queue_head = queue.enqueue(
            task_id=prepared.task_id,
            run_number=prepared.run_number,
            source_sha=source_sha,
            source_base_sha=prepared.task_base_sha,
        )
        if not is_queue_head:
            return MergeResult(
                status="pending_merge",
                merge_queue_seq=queue_entry.seq,
                detail="Waiting for an earlier Main Task merge",
            )

        def queued_result(**values: object) -> MergeResult:
            return MergeResult(merge_queue_seq=queue_entry.seq, **values)

        with target_branch_git_lock(repo, prepared.target_branch):
            target_head = branch_head(repo, prepared.target_branch)
            if not target_head:
                return queued_result(status="waiting_target_branch")
            if not is_ancestor(repo, prepared.task_base_sha, target_head):
                return queued_result(
                    status="waiting_target_history",
                    target_head_sha=target_head,
                    detail="Task source base is no longer an ancestor of captured target branch",
                )
            if is_ancestor(repo, source_sha, target_head):
                managed = _delivery_path(prepared)
                cleanup = _cleanup_delivery(repo, managed, prepared.target_branch) if managed.exists() else ""
                queue.complete(queue_entry)
                return queued_result(
                    status="merged",
                    target_head_sha=target_head,
                    merged_target_head_sha=target_head,
                    detail=cleanup,
                )

            target, managed, blocked = _find_target_worktree(prepared)
            if blocked is not None:
                return blocked
            assert target is not None
            cleanup_needed = managed
            try:
                current_branch = git(target, "branch", "--show-current").stdout.strip()
                current_head = git(target, "rev-parse", "HEAD").stdout.strip()
                if current_branch != prepared.target_branch or current_head != target_head:
                    return queued_result(
                        status="waiting_target_workspace",
                        target_head_sha=target_head,
                        target_worktree=target,
                        detail="Target worktree no longer matches captured target branch HEAD",
                    )

                operations = active_git_operations(target)
                if operations:
                    if managed and operations == ("MERGE_HEAD",):
                        merge_head = git(
                            target, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False
                        ).stdout.strip()
                        if merge_head == source_sha:
                            _abort_owned_merge(target, source_sha)
                            operations = ()
                    if operations:
                        return queued_result(
                            status="waiting_target_workspace",
                            target_head_sha=target_head,
                            target_worktree=target,
                            detail="Target worktree has an active Git operation: " + ", ".join(operations),
                        )

                if _target_has_source_changes(prepared, target):
                    return queued_result(
                        status="waiting_target_clean",
                        target_head_sha=target_head,
                        target_worktree=target,
                        detail="Captured target worktree has uncommitted changes",
                    )

                merge = git(
                    target,
                    "merge",
                    "--no-ff",
                    "--no-commit",
                    prepared.task_branch,
                    check=False,
                )
                if merge.returncode != 0:
                    conflicts = tuple(
                        line.strip()
                        for line in git(
                            target, "diff", "--name-only", "--diff-filter=U", check=False
                        ).stdout.splitlines()
                        if line.strip()
                    )
                    if conflicts:
                        _abort_owned_merge(target, source_sha)
                        return queued_result(
                            status="conflict",
                            target_head_sha=target_head,
                            target_worktree=target,
                            real_merge_failure=True,
                            conflict_files=conflicts,
                            detail=(merge.stderr or merge.stdout or "").strip(),
                        )
                    _abort_owned_merge(target, source_sha)
                    return queued_result(
                        status="technical_error",
                        target_head_sha=target_head,
                        target_worktree=target,
                        verdict="TECHNICAL_ERROR",
                        detail=(merge.stderr or merge.stdout or "").strip(),
                    )

                index_tree = git(target, "write-tree", check=False)
                working_diff = git(target, "diff", "--quiet", check=False)
                if index_tree.returncode != 0 or working_diff.returncode != 0:
                    _abort_owned_merge(target, source_sha)
                    return queued_result(
                        status="technical_error",
                        target_head_sha=target_head,
                        target_worktree=target,
                        verdict="TECHNICAL_ERROR",
                        detail="Uncommitted merge tree was not stable before validation",
                    )

                validation_required = target_head != prepared.task_base_sha
                verdict = "PASS"
                if validation_required:
                    if validate is None:
                        _abort_owned_merge(target, source_sha)
                        return queued_result(
                            status="validation_required",
                            target_head_sha=target_head,
                            target_worktree=target,
                            validation_required=True,
                            detail="Merged tree differs from the Task validation base",
                        )
                    try:
                        verdict = str(validate(_target_project(prepared, target)) or "").strip().upper()
                    except Exception as exc:
                        _abort_owned_merge(target, source_sha)
                        return queued_result(
                            status="technical_error",
                            target_head_sha=target_head,
                            target_worktree=target,
                            validation_required=True,
                            verdict="TECHNICAL_ERROR",
                            detail=f"{type(exc).__name__}: {exc}",
                        )
                    if verdict not in _VALIDATION_RESULTS:
                        _abort_owned_merge(target, source_sha)
                        return queued_result(
                            status="technical_error",
                            target_head_sha=target_head,
                            target_worktree=target,
                            validation_required=True,
                            verdict="TECHNICAL_ERROR",
                            detail=f"Unsupported merge validation verdict: {verdict or '<empty>'}",
                        )
                    if verdict == "SOURCE_FAIL":
                        _abort_owned_merge(target, source_sha)
                        return queued_result(
                            status="source_fail",
                            target_head_sha=target_head,
                            target_worktree=target,
                            validation_required=True,
                            verdict=verdict,
                            real_merge_failure=True,
                        )
                    if verdict == "TECHNICAL_ERROR":
                        _abort_owned_merge(target, source_sha)
                        return queued_result(
                            status="technical_error",
                            target_head_sha=target_head,
                            target_worktree=target,
                            validation_required=True,
                            verdict=verdict,
                        )

                if not _transaction_owned(
                    prepared,
                    target,
                    target_head=target_head,
                    source_sha=source_sha,
                    expected_index_tree=index_tree.stdout.strip(),
                ):
                    _abort_owned_merge(target, source_sha)
                    return queued_result(
                        status="technical_error",
                        target_head_sha=target_head,
                        target_worktree=target,
                        validation_required=validation_required,
                        verdict="TECHNICAL_ERROR",
                        detail="Merge transaction ownership changed before commit",
                    )

                message = str(commit_message or "").strip() or (
                    f"Merge {prepared.task_id} run {prepared.run_number}"
                )
                git(
                    target,
                    "-c",
                    "user.name=AI Task Runner",
                    "-c",
                    "user.email=ai-task-runner@localhost",
                    "commit",
                    "-m",
                    message,
                )
                merged = git(target, "rev-parse", "HEAD").stdout.strip()
                if not is_ancestor(repo, source_sha, merged):
                    raise WorkspaceError("Committed merge does not contain Task snapshot")
                cleanup_needed = False
                cleanup_error = _cleanup_delivery(repo, target, prepared.target_branch) if managed else ""
                queue.complete(queue_entry)
                return queued_result(
                    status="merged",
                    target_head_sha=target_head,
                    merged_target_head_sha=merged,
                    target_worktree=target,
                    validation_required=validation_required,
                    verdict=verdict if validation_required else "",
                    detail=cleanup_error,
                )
            finally:
                if cleanup_needed and managed:
                    _cleanup_delivery(repo, target, prepared.target_branch)
