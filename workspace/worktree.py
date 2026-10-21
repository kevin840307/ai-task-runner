"""Deterministic Git worktree mechanics for the workspace adapter."""
from __future__ import annotations

import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from .model import WorkspaceError

LOCK_TIMEOUT_SECONDS = 8.0
LOCK_POLL_SECONDS = 0.05
STALE_LOCK_SECONDS = 60.0
LOCK_FILENAME = "ai-task-runner-workspace.lock"


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


def git(
    cwd: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = ["git", *args]
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkspaceError(f"Git command failed: {' '.join(command)}: {exc}") from exc
    if check and result.returncode != 0:
        detail = _detail(result)
        suffix = f": {detail}" if detail else ""
        raise WorkspaceError(f"Git command failed ({result.returncode}): {' '.join(command)}{suffix}")
    return result


def repository_root(project_root: Path) -> Path:
    project = Path(project_root).expanduser().resolve()
    if not project.is_dir():
        raise WorkspaceError(f"Project does not exist: {project}")
    result = git(project, "rev-parse", "--show-toplevel")
    value = result.stdout.strip()
    if not value:
        raise WorkspaceError(f"Cannot resolve Git repository for Project: {project}")
    root = Path(value).resolve()
    try:
        project.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("Project root is outside the resolved Git repository") from exc
    return root


def repository_identity(repo: Path) -> Path:
    result = git(repo, "rev-parse", "--git-common-dir")
    raw = Path(result.stdout.strip())
    common = raw if raw.is_absolute() else repo / raw
    return common.resolve()


def capture_target(repo: Path) -> tuple[str, str]:
    branch = git(repo, "branch", "--show-current").stdout.strip()
    if not branch:
        raise WorkspaceError("Project checkout is detached HEAD; select a target branch before starting a Task")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    branch_head = git(repo, "rev-parse", "--verify", f"refs/heads/{branch}").stdout.strip()
    if not head or branch_head != head:
        raise WorkspaceError("Project branch/HEAD changed while capturing Task target")
    return branch, head


def branch_head(repo: Path, branch: str) -> str:
    result = git(repo, "rev-parse", "--verify", f"refs/heads/{branch}", check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = git(repo, "merge-base", "--is-ancestor", ancestor, descendant, check=False)
    if result.returncode not in (0, 1):
        raise WorkspaceError(f"Cannot verify Git ancestry: {_detail(result)}")
    return result.returncode == 0


def verify_worktree(
    repo: Path,
    path: Path,
    *,
    expected_branch: str,
    expected_base_sha: str,
) -> None:
    worktree = path.resolve()
    if not worktree.is_dir():
        raise WorkspaceError(f"Expected Task worktree is missing: {worktree}")
    found_root = Path(git(worktree, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if found_root != worktree:
        raise WorkspaceError(f"Existing Task path is not a worktree root: {worktree}")
    if repository_identity(found_root) != repository_identity(repo):
        raise WorkspaceError(f"Task worktree belongs to another Git repository: {worktree}")
    branch = git(worktree, "branch", "--show-current").stdout.strip()
    if branch != expected_branch:
        raise WorkspaceError(
            f"Task worktree branch mismatch: expected {expected_branch}, found {branch or 'detached/unknown'}"
        )
    head = git(worktree, "rev-parse", "HEAD").stdout.strip()
    if not is_ancestor(repo, expected_base_sha, head):
        raise WorkspaceError("Task worktree HEAD no longer descends from the captured Task base")


@contextmanager
def repository_git_lock(repo: Path):
    """Short cross-process lock for repository ref/worktree mutations only."""
    common = repository_identity(repo)
    common.mkdir(parents=True, exist_ok=True)
    lock = common / LOCK_FILENAME
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    handle: int | None = None
    while handle is None:
        try:
            handle = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > STALE_LOCK_SECONDS:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise WorkspaceError(f"Timed out waiting for repository Git lock: {lock}")
            time.sleep(LOCK_POLL_SECONDS)
    try:
        os.write(handle, f"{os.getpid()}\n".encode("ascii"))
        yield
    finally:
        os.close(handle)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def add_or_reuse_worktree(
    repo: Path,
    path: Path,
    *,
    branch: str,
    base_sha: str,
) -> None:
    """Create one Task worktree, or idempotently reuse its exact run identity."""
    worktree = path.resolve()
    with repository_git_lock(repo):
        if worktree.exists():
            verify_worktree(
                repo,
                worktree,
                expected_branch=branch,
                expected_base_sha=base_sha,
            )
            return

        worktree.parent.mkdir(parents=True, exist_ok=True)
        existing = branch_head(repo, branch)
        if existing:
            if existing != base_sha:
                raise WorkspaceError(
                    f"Task branch already exists at another commit: {branch} ({existing})"
                )
            git(repo, "worktree", "add", str(worktree), branch)
        else:
            git(repo, "worktree", "add", "-b", branch, str(worktree), base_sha)

        verify_worktree(
            repo,
            worktree,
            expected_branch=branch,
            expected_base_sha=base_sha,
        )
