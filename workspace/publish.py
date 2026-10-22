"""Explicit remote publication for completed Task results only."""
from __future__ import annotations

from .model import PreparedWorkspace, PublishResult, WorkspaceError
from .worktree import branch_head, git, repository_identity


class PublishManager:
    """Publish one durable local branch without changing Task merge/recovery state."""

    def publish(
        self,
        prepared: PreparedWorkspace,
        *,
        branch: str,
        expected_sha: str,
    ) -> PublishResult:
        repo = prepared.repository_root.resolve()
        if repository_identity(repo) != prepared.repository_identity.resolve():
            raise WorkspaceError("Workspace repository identity changed before Publish")
        branch_name = str(branch or "").strip()
        sha = str(expected_sha or "").strip()
        if not branch_name or not sha:
            raise WorkspaceError("Publish requires a durable branch and SHA")
        if branch_head(repo, branch_name) != sha:
            raise WorkspaceError("Publish branch no longer matches durable Task result")

        remote = "origin"
        remote_check = git(repo, "remote", "get-url", remote, check=False)
        if remote_check.returncode != 0:
            return PublishResult(
                "remote_unavailable",
                branch_name,
                sha,
                remote,
                (remote_check.stderr or remote_check.stdout or "origin remote is unavailable").strip()[-4000:],
            )

        result = git(
            repo,
            "push",
            "--porcelain",
            remote,
            f"refs/heads/{branch_name}:refs/heads/{branch_name}",
            check=False,
        )
        detail = (result.stderr or result.stdout or "").strip()[-4000:]
        if result.returncode != 0:
            return PublishResult("rejected", branch_name, sha, remote, detail)
        status = "already_published" if "[up to date]" in detail.lower() else "published"
        return PublishResult(status, branch_name, sha, remote, detail)


__all__ = ["PublishManager"]
