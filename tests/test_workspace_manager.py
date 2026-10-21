from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from workspace import WorkspaceBlockedError, WorkspaceError, WorkspaceManager, resolve_workspace_mode


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _repo(tmp_path: Path, *, branch: str = "feature/base") -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "workspace-test@example.invalid")
    _git(repo, "config", "user.name", "Workspace Test")
    (repo / "app.txt").write_text("committed\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", branch)
    return repo


@pytest.mark.parametrize(
    ("requested", "policy", "busy", "concurrent", "effective"),
    [
        ("auto", "busy-worktree", False, False, "main"),
        ("auto", "busy-worktree", True, False, "worktree"),
        ("auto", "busy-worktree", True, True, "worktree"),
        ("auto", "always-worktree", False, False, "worktree"),
        ("auto", "always-worktree", True, True, "worktree"),
        ("auto", "always-main", False, False, "main"),
        ("auto", "always-main", True, True, "main"),
        ("main", "busy-worktree", False, False, "main"),
        ("main", "busy-worktree", True, True, "main"),
        ("worktree", "always-main", True, False, "worktree"),
    ],
)
def test_workspace_resolver_policy_matrix(requested, policy, busy, concurrent, effective):
    result = resolve_workspace_mode(
        requested,
        auto_policy=policy,
        main_running=busy,
        allow_concurrent_main_tasks=concurrent,
    )
    assert result.requested_mode == requested
    assert result.effective_mode == effective


@pytest.mark.parametrize("requested,policy", [("main", "busy-worktree"), ("auto", "always-main")])
def test_workspace_resolver_blocks_busy_main_when_concurrency_is_off(requested, policy):
    with pytest.raises(WorkspaceBlockedError, match="concurrent Main"):
        resolve_workspace_mode(
            requested,
            auto_policy=policy,
            main_running=True,
            allow_concurrent_main_tasks=False,
        )


def test_prepare_captures_branch_and_head_and_excludes_uncommitted_project_changes(tmp_path: Path):
    repo = _repo(tmp_path)
    captured = _git(repo, "rev-parse", "HEAD")
    (repo / "app.txt").write_text("dirty user change\n", encoding="utf-8")

    prepared = WorkspaceManager().prepare(
        repo,
        task_id="task-0123456789abcdef0123456789abcdef",
        run_number=1,
        requested_mode="auto",
        execution_settings={
            "auto_workspace_policy": "busy-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )

    assert prepared.effective_mode == "main"
    assert prepared.target_branch == "feature/base"
    assert prepared.target_head_sha_at_start == captured
    assert prepared.task_base_sha == captured
    assert prepared.task_branch == "local/task/task-0123456789abcdef0123456789abcdef-r1"
    assert prepared.worktree_path.parent == tmp_path / ".worktrees" / repo.name
    assert prepared.project_root == prepared.worktree_path
    assert (prepared.project_root / "app.txt").read_text(encoding="utf-8") == "committed\n"
    assert _git(repo, "rev-parse", prepared.task_branch) == captured
    assert _git(prepared.worktree_path, "branch", "--show-current") == prepared.task_branch
    assert (repo / "app.txt").read_text(encoding="utf-8") == "dirty user change\n"


def test_prepare_is_idempotent_for_same_task_run_identity(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    args = dict(
        task_id="task-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        run_number=2,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-main",
            "allow_concurrent_main_tasks": False,
        },
        main_running=True,
    )

    first = manager.prepare(repo, **args)
    (first.worktree_path / "local.txt").write_text("resume me\n", encoding="utf-8")
    second = manager.prepare(repo, **args)

    assert second == first
    assert (second.worktree_path / "local.txt").read_text(encoding="utf-8") == "resume me\n"
    listed = _git(repo, "worktree", "list", "--porcelain")
    paths = [
        Path(line.removeprefix("worktree ")).resolve()
        for line in listed.splitlines()
        if line.startswith("worktree ")
    ]
    assert paths.count(first.worktree_path.resolve()) == 1


def test_prepare_maps_project_subdirectory_into_worktree(tmp_path: Path):
    repo = _repo(tmp_path)
    project = repo / "service"
    project.mkdir()
    (project / "service.txt").write_text("service\n", encoding="utf-8")
    _git(repo, "add", "service/service.txt")
    _git(repo, "commit", "-m", "service")

    prepared = WorkspaceManager().prepare(
        project,
        task_id="task-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        run_number=1,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )

    assert prepared.repository_root == repo.resolve()
    assert prepared.project_root == prepared.worktree_path / "service"
    assert (prepared.project_root / "service.txt").read_text(encoding="utf-8") == "service\n"


def test_prepare_rejects_detached_project_head(tmp_path: Path):
    repo = _repo(tmp_path)
    _git(repo, "checkout", "--detach")

    with pytest.raises(WorkspaceError, match="detached HEAD"):
        WorkspaceManager().prepare(
            repo,
            task_id="task-cccccccccccccccccccccccccccccccc",
            run_number=1,
            requested_mode="main",
            execution_settings={
                "auto_workspace_policy": "always-main",
                "allow_concurrent_main_tasks": True,
            },
            main_running=False,
        )


def test_prepare_fails_closed_when_existing_task_branch_points_elsewhere(tmp_path: Path):
    repo = _repo(tmp_path)
    task_id = "task-dddddddddddddddddddddddddddddddd"
    branch = f"local/task/{task_id}-r1"
    _git(repo, "branch", branch)
    (repo / "other.txt").write_text("other\n", encoding="utf-8")
    _git(repo, "add", "other.txt")
    _git(repo, "commit", "-m", "move target")
    # Keep the Task branch on the old commit but capture the new target HEAD.

    with pytest.raises(WorkspaceError, match="another commit"):
        WorkspaceManager().prepare(
            repo,
            task_id=task_id,
            run_number=1,
            requested_mode="worktree",
            execution_settings={
                "auto_workspace_policy": "always-worktree",
                "allow_concurrent_main_tasks": False,
            },
            main_running=False,
        )


def test_workspace_identity_rejects_invalid_task_or_run(tmp_path: Path):
    repo = _repo(tmp_path)
    settings = {
        "auto_workspace_policy": "always-worktree",
        "allow_concurrent_main_tasks": False,
    }
    manager = WorkspaceManager()

    with pytest.raises(WorkspaceError, match="Task id"):
        manager.prepare(
            repo,
            task_id="../escape",
            run_number=1,
            requested_mode="worktree",
            execution_settings=settings,
            main_running=False,
        )
    with pytest.raises(WorkspaceError, match="positive integer"):
        manager.prepare(
            repo,
            task_id="task-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            run_number=0,
            requested_mode="worktree",
            execution_settings=settings,
            main_running=False,
        )
