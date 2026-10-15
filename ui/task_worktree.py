"""Small Git worktree provisioning adapter for Task workspaces.

This owns workspace lifecycle only. It never launches Runner work, merges branches,
rebases, cherry-picks, or implements scheduling.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


class WorktreeError(ValueError):
    pass


def _git(repo: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise WorktreeError(detail or f"git {' '.join(args)} failed")
    return result


def git_root(path: Path) -> Path:
    result = _git(path, ["rev-parse", "--show-toplevel"])
    root = Path(result.stdout.strip()).resolve()
    if not root.is_dir():
        raise WorktreeError("Git repository root is unavailable")
    return root


def list_worktrees(repo: Path) -> list[dict]:
    root = git_root(repo)
    result = _git(root, ["worktree", "list", "--porcelain"])
    rows: list[dict] = []
    current: dict = {}
    for line in result.stdout.splitlines() + [""]:
        if not line.strip():
            if current.get("path"):
                current["is_main"] = Path(current["path"]).resolve() == root
                rows.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = str(Path(value).resolve())
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif key == "detached":
            current["detached"] = True
    return rows


def _safe_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return token[:40] or "task"


def create_task_worktree(repo: Path, task_id: str) -> dict:
    root = git_root(repo)
    token = _safe_token(task_id[:16])
    worktree_root = root.parent / f"{root.name}-worktrees"
    worktree = (worktree_root / token).resolve()
    branch = f"ai/task-{token}"
    if worktree.exists():
        raise WorktreeError(f"Task worktree already exists: {worktree}")
    existing = {row.get("branch") for row in list_worktrees(root)}
    if branch in existing:
        raise WorktreeError(f"Task branch is already checked out: {branch}")
    worktree_root.mkdir(parents=True, exist_ok=True)
    try:
        _git(root, ["worktree", "add", "-b", branch, str(worktree), "HEAD"])
    except Exception:
        try:
            if worktree.exists() and not any(worktree.iterdir()):
                worktree.rmdir()
        except OSError:
            pass
        raise
    return {
        "kind": "worktree",
        "path": str(worktree),
        "branch": branch,
        "source_root": str(root),
        "managed": True,
    }


def attach_existing_worktree(repo: Path, path: str) -> dict:
    root = git_root(repo)
    candidate = Path(path).expanduser().resolve()
    row = next(
        (item for item in list_worktrees(root) if Path(item["path"]).resolve() == candidate),
        None,
    )
    if row is None:
        raise WorktreeError("Selected path is not a Git worktree of this Chat project")
    if row.get("is_main"):
        return {
            "kind": "main",
            "path": str(root),
            "branch": row.get("branch", ""),
            "source_root": str(root),
            "managed": False,
        }
    return {
        "kind": "worktree",
        "path": str(candidate),
        "branch": str(row.get("branch") or ""),
        "source_root": str(root),
        "managed": False,
    }


def archive_runtime(worktree: Path, archive: Path) -> str:
    runtime = worktree / ".ai-task-runner"
    if not runtime.is_dir():
        return ""
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        # Cleanup may be retried after a later Git worktree removal failure.
        # Reuse the already archived evidence instead of failing the retry.
        return str(archive)
    shutil.copytree(runtime, archive)
    return str(archive)


def remove_task_worktree(repo: Path, worktree: Path) -> None:
    root = git_root(repo)
    candidate = worktree.expanduser().resolve()
    row = next(
        (item for item in list_worktrees(root) if Path(item["path"]).resolve() == candidate),
        None,
    )
    if row is None or row.get("is_main"):
        raise WorktreeError("Task workspace is not a removable Git worktree")
    # Never use --force: dirty/uncommitted user work must fail closed.
    _git(root, ["worktree", "remove", str(candidate)])
