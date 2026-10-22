from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from workspace import PublishManager, WorkspaceError, WorkspaceManager


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _fixture(tmp_path: Path):
    repo = tmp_path / "project"
    remote = tmp_path / "origin.git"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Publish Test")
    _git(repo, "config", "user.email", "publish-test@example.invalid")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "base")
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        check=True,
        text=True,
        capture_output=True,
    )
    _git(repo, "remote", "add", "origin", str(remote))

    manager = WorkspaceManager(worktree_root=tmp_path / "worktrees")
    prepared = manager.prepare(
        repo,
        task_id="task-" + "a" * 32,
        run_number=1,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )
    (prepared.worktree_path / "result.txt").write_text("done\n", encoding="utf-8")
    snapshot = manager.snapshot_result(prepared)
    return repo, remote, prepared, snapshot


def test_explicit_publish_pushes_durable_branch_without_force(tmp_path: Path):
    _repo, remote, prepared, snapshot = _fixture(tmp_path)
    publisher = PublishManager()

    result = publisher.publish(
        prepared,
        branch=prepared.task_branch,
        expected_sha=snapshot.task_snapshot_sha,
    )

    assert result.status == "published"
    remote_sha = _git(remote, "rev-parse", f"refs/heads/{prepared.task_branch}")
    assert remote_sha == snapshot.task_snapshot_sha

    repeated = publisher.publish(
        prepared,
        branch=prepared.task_branch,
        expected_sha=snapshot.task_snapshot_sha,
    )
    assert repeated.status == "already_published"


def test_publish_fails_closed_when_local_branch_moved_after_durable_result(tmp_path: Path):
    _repo, _remote, prepared, snapshot = _fixture(tmp_path)
    (prepared.worktree_path / "late.txt").write_text("late\n", encoding="utf-8")
    _git(prepared.worktree_path, "add", "late.txt")
    _git(prepared.worktree_path, "commit", "-m", "late local change")

    with pytest.raises(WorkspaceError, match="no longer matches durable Task result"):
        PublishManager().publish(
            prepared,
            branch=prepared.task_branch,
            expected_sha=snapshot.task_snapshot_sha,
        )
