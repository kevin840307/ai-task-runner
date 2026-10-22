"""Deterministic Git worktree mechanics for the workspace adapter."""
from __future__ import annotations

import hashlib
import os
import subprocess
import threading
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
def _git_file_lock(repo: Path, filename: str, *, heartbeat: bool = False):
    common = repository_identity(repo)
    common.mkdir(parents=True, exist_ok=True)
    lock = common / filename
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
                raise WorkspaceError(f"Timed out waiting for Git lock: {lock}")
            time.sleep(LOCK_POLL_SECONDS)
    stop = threading.Event()
    pulse: threading.Thread | None = None
    try:
        os.write(handle, f"{os.getpid()}\n".encode("ascii"))
        if heartbeat:
            def keep_fresh() -> None:
                interval = max(1.0, STALE_LOCK_SECONDS / 3)
                while not stop.wait(interval):
                    try:
                        os.utime(lock, None)
                    except OSError:
                        return
            pulse = threading.Thread(
                target=keep_fresh,
                name="workspace-git-lock-heartbeat",
                daemon=True,
            )
            pulse.start()
        yield
    finally:
        stop.set()
        if pulse is not None:
            pulse.join(timeout=1)
        os.close(handle)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def repository_git_lock(repo: Path):
    """Short cross-process lock for repository ref/worktree mutations only."""
    with _git_file_lock(repo, LOCK_FILENAME):
        yield


@contextmanager
def target_branch_git_lock(repo: Path, branch: str):
    """Serialize delivery transactions for one repository + target branch."""
    key = hashlib.sha256(str(branch).encode("utf-8")).hexdigest()[:24]
    with _git_file_lock(
        repo,
        f"ai-task-runner-merge-{key}.lock",
        heartbeat=True,
    ):
        yield

@contextmanager
def merge_queue_lock(repo: Path, branch: str):
    """Serialize only durable FIFO queue state updates for one target branch."""
    key = hashlib.sha256(str(branch).encode("utf-8")).hexdigest()[:24]
    with _git_file_lock(repo, f"ai-task-runner-merge-queue-{key}.lock"):
        yield


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


_OPERATION_PATHS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "rebase-merge",
    "rebase-apply",
    "BISECT_LOG",
)


def _git_path(worktree: Path, name: str) -> Path:
    raw = Path(git(worktree, "rev-parse", "--git-path", name).stdout.strip())
    return (raw if raw.is_absolute() else worktree / raw).resolve()


def active_git_operations(worktree: Path) -> tuple[str, ...]:
    return tuple(name for name in _OPERATION_PATHS if _git_path(worktree, name).exists())


def active_git_operation(worktree: Path) -> str:
    values = active_git_operations(worktree)
    return values[0] if values else ""


def cleanup_owned_worktree(
    repo: Path,
    path: Path,
    *,
    expected_branch: str,
    expected_base_sha: str,
) -> str:
    """Remove one owned Task/Recovery worktree and local branch, idempotently."""
    worktree = path.resolve()
    with repository_git_lock(repo):
        head = branch_head(repo, expected_branch)
        if not worktree.exists():
            # Recover safely from a crash after worktree removal but before
            # local branch deletion. Pruning only stale Git worktree metadata.
            git(repo, "worktree", "prune")
            if not head:
                return "already_cleaned"
            if not is_ancestor(repo, expected_base_sha, head):
                raise WorkspaceError(
                    "Cleanup branch no longer descends from the captured source base"
                )
            deleted = git(repo, "branch", "-D", expected_branch, check=False)
            if deleted.returncode != 0:
                raise WorkspaceError(
                    "Could not delete cleaned Task branch: "
                    + (_detail(deleted) or expected_branch)
                )
            return "cleaned"

        verify_worktree(
            repo,
            worktree,
            expected_branch=expected_branch,
            expected_base_sha=expected_base_sha,
        )
        operation = active_git_operation(worktree)
        if operation:
            raise WorkspaceError(
                f"Task worktree has an active Git operation: {operation}"
            )
        head = git(worktree, "rev-parse", "HEAD").stdout.strip()
        removed = git(repo, "worktree", "remove", "--force", str(worktree), check=False)
        if removed.returncode != 0:
            raise WorkspaceError(
                "Could not remove Task worktree: " + (_detail(removed) or str(worktree))
            )
        current = branch_head(repo, expected_branch)
        if current and current != head:
            raise WorkspaceError(
                "Task branch changed while its worktree was being cleaned"
            )
        if current:
            deleted = git(repo, "branch", "-D", expected_branch, check=False)
            if deleted.returncode != 0:
                raise WorkspaceError(
                    "Could not delete cleaned Task branch: "
                    + (_detail(deleted) or expected_branch)
                )
        return "cleaned"


def snapshot_task_result(
    repo: Path,
    path: Path,
    *,
    expected_branch: str,
    expected_base_sha: str,
    commit_message: str,
    excluded_paths: tuple[Path, ...] = (),
) -> tuple[str, bool, bool]:
    """Commit remaining Task changes without rewriting prior Agent commits."""
    message = str(commit_message or "").strip()
    if not message:
        raise WorkspaceError("Task snapshot commit message is required")
    worktree = path.resolve()
    with repository_git_lock(repo):
        verify_worktree(
            repo,
            worktree,
            expected_branch=expected_branch,
            expected_base_sha=expected_base_sha,
        )
        operation = active_git_operation(worktree)
        if operation:
            raise WorkspaceError(
                f"Task worktree has an active Git operation: {operation}"
            )
        before = git(worktree, "rev-parse", "HEAD").stdout.strip()
        dirty = bool(git(worktree, "status", "--porcelain=v1", "-z").stdout)
        if dirty:
            git(worktree, "add", "-A")
            for value in excluded_paths:
                excluded = Path(value).expanduser().resolve()
                try:
                    relative = excluded.relative_to(worktree)
                except ValueError as exc:
                    raise WorkspaceError(
                        f"Snapshot exclude path is outside Task worktree: {excluded}"
                    ) from exc
                if not relative.parts:
                    raise WorkspaceError("Snapshot exclude path cannot be the Task worktree root")
                git(
                    worktree,
                    "reset",
                    "--quiet",
                    "HEAD",
                    "--",
                    relative.as_posix(),
                )
            staged = git(
                worktree,
                "diff",
                "--cached",
                "--quiet",
                check=False,
            )
            if staged.returncode not in (0, 1):
                raise WorkspaceError(f"Cannot inspect staged Task snapshot: {_detail(staged)}")
            verify_worktree(
                repo,
                worktree,
                expected_branch=expected_branch,
                expected_base_sha=expected_base_sha,
            )
            operation = active_git_operation(worktree)
            if operation:
                raise WorkspaceError(
                    f"Task worktree entered an active Git operation: {operation}"
                )
            if staged.returncode == 1:
                git(
                    worktree,
                    "-c",
                    "user.name=AI Task Runner",
                    "-c",
                    "user.email=ai-task-runner@localhost",
                    "commit",
                    "-m",
                    message,
                )
        after = git(worktree, "rev-parse", "HEAD").stdout.strip()
        verify_worktree(
            repo,
            worktree,
            expected_branch=expected_branch,
            expected_base_sha=expected_base_sha,
        )
        diff = git(
            worktree,
            "diff",
            "--quiet",
            expected_base_sha,
            after,
            "--",
            check=False,
        )
        if diff.returncode not in (0, 1):
            raise WorkspaceError(f"Cannot compare Task snapshot with its base: {_detail(diff)}")
        return after, diff.returncode == 0, after != before
