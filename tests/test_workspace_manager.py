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
    assert prepared.source_project_root == repo.resolve()
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


def test_snapshot_commits_remaining_changes_and_preserves_prior_agent_commits(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    prepared = manager.prepare(
        repo,
        task_id="task-11111111111111111111111111111111",
        run_number=1,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )

    (prepared.worktree_path / "agent.txt").write_text("agent commit\n", encoding="utf-8")
    _git(prepared.worktree_path, "add", "agent.txt")
    _git(prepared.worktree_path, "commit", "-m", "agent commit")
    agent_sha = _git(prepared.worktree_path, "rev-parse", "HEAD")
    (prepared.worktree_path / "remaining.txt").write_text("remaining\n", encoding="utf-8")

    snapshot = manager.snapshot_result(prepared)

    assert snapshot.no_changes is False
    assert snapshot.created_commit is True
    assert snapshot.task_snapshot_sha == _git(prepared.worktree_path, "rev-parse", "HEAD")
    assert snapshot.task_snapshot_sha != agent_sha
    assert _git(repo, "merge-base", "--is-ancestor", agent_sha, snapshot.task_snapshot_sha) == ""
    assert (prepared.worktree_path / "remaining.txt").is_file()


def test_snapshot_clean_base_returns_no_changes_without_empty_commit(tmp_path: Path):
    repo = _repo(tmp_path)
    prepared = WorkspaceManager().prepare(
        repo,
        task_id="task-22222222222222222222222222222222",
        run_number=1,
        requested_mode="main",
        execution_settings={
            "auto_workspace_policy": "always-main",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )
    before = _git(prepared.worktree_path, "rev-parse", "HEAD")

    snapshot = WorkspaceManager().snapshot_result(prepared)

    assert snapshot.no_changes is True
    assert snapshot.created_commit is False
    assert snapshot.task_snapshot_sha == before
    assert _git(prepared.worktree_path, "rev-list", "--count", prepared.task_base_sha + "..HEAD") == "0"


def test_snapshot_clean_agent_commit_is_deliverable_without_new_commit(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    prepared = manager.prepare(
        repo,
        task_id="task-33333333333333333333333333333333",
        run_number=1,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )
    (prepared.worktree_path / "agent.txt").write_text("agent\n", encoding="utf-8")
    _git(prepared.worktree_path, "add", "agent.txt")
    _git(prepared.worktree_path, "commit", "-m", "agent")
    before = _git(prepared.worktree_path, "rev-parse", "HEAD")

    snapshot = manager.snapshot_result(prepared)

    assert snapshot.no_changes is False
    assert snapshot.created_commit is False
    assert snapshot.task_snapshot_sha == before


def test_snapshot_fails_closed_on_branch_or_git_operation_mismatch(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    prepared = manager.prepare(
        repo,
        task_id="task-44444444444444444444444444444444",
        run_number=1,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )
    _git(prepared.worktree_path, "checkout", "--detach")
    with pytest.raises(WorkspaceError, match="branch mismatch"):
        manager.snapshot_result(prepared)

    _git(prepared.worktree_path, "checkout", prepared.task_branch)
    raw = _git(prepared.worktree_path, "rev-parse", "--git-path", "MERGE_HEAD")
    marker = Path(raw)
    if not marker.is_absolute():
        marker = prepared.worktree_path / marker
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(prepared.task_base_sha + "\n", encoding="ascii")
    try:
        with pytest.raises(WorkspaceError, match="active Git operation"):
            manager.snapshot_result(prepared)
    finally:
        marker.unlink(missing_ok=True)


def test_snapshot_rejects_task_branch_that_no_longer_descends_from_base(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    prepared = manager.prepare(
        repo,
        task_id="task-55555555555555555555555555555555",
        run_number=1,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )
    unrelated = _git(
        prepared.worktree_path,
        "commit-tree",
        _git(prepared.worktree_path, "mktree"),
        "-m",
        "unrelated",
    )
    _git(prepared.worktree_path, "reset", "--hard", unrelated)

    with pytest.raises(WorkspaceError, match="no longer descends"):
        manager.snapshot_result(prepared)


def test_restore_keeps_original_target_after_project_branch_advances(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    prepared = manager.prepare(
        repo,
        task_id="task-66666666666666666666666666666666",
        run_number=1,
        requested_mode="main",
        execution_settings={
            "auto_workspace_policy": "always-main",
            "allow_concurrent_main_tasks": True,
        },
        main_running=False,
    )
    original = prepared.target_head_sha_at_start
    (repo / "later.txt").write_text("later target change\n", encoding="utf-8")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-m", "advance target")
    assert _git(repo, "rev-parse", "HEAD") != original

    restored = manager.restore(prepared.as_dict())

    assert restored == prepared
    assert restored.target_head_sha_at_start == original
    assert restored.task_base_sha == original
    assert _git(restored.worktree_path, "rev-parse", "HEAD") == original


def test_restore_rejects_tampered_workspace_metadata(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    prepared = manager.prepare(
        repo,
        task_id="task-77777777777777777777777777777777",
        run_number=3,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )
    value = prepared.as_dict()
    value["task_branch"] = "local/task/another-run"

    with pytest.raises(WorkspaceError, match="Task branch"):
        manager.restore(value)


def test_prepare_recovery_uses_latest_target_and_preserves_current_source(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    source = manager.prepare(
        repo,
        task_id="task-recovery111111111111111111111111",
        run_number=1,
        requested_mode="main",
        execution_settings={
            "auto_workspace_policy": "always-main",
            "allow_concurrent_main_tasks": True,
        },
        main_running=False,
    )
    (source.worktree_path / "feature.txt").write_text("task result\n", encoding="utf-8")
    snapshot = manager.snapshot_result(source)
    original_source_head = _git(source.worktree_path, "rev-parse", "HEAD")

    (repo / "target.txt").write_text("latest target\n", encoding="utf-8")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "advance target")
    latest_target = _git(repo, "rev-parse", "HEAD")

    recovery = manager.prepare_recovery(source, snapshot, failure_number=1)

    assert recovery.task_branch == f"local/recovery/{source.task_id}-r1-f1"
    assert recovery.task_base_sha == latest_target
    assert recovery.target_head_sha_at_start == latest_target
    assert recovery.project_root == recovery.worktree_path
    assert (recovery.project_root / "target.txt").read_text(encoding="utf-8") == "latest target\n"
    assert not (recovery.project_root / "feature.txt").exists()
    assert (source.worktree_path / "feature.txt").read_text(encoding="utf-8") == "task result\n"
    assert _git(source.worktree_path, "rev-parse", "HEAD") == original_source_head

    patch = manager.recovery_patch(source, snapshot)
    assert "feature.txt" in patch
    assert "task result" in patch
    assert manager.restore_merge_source(recovery.as_dict()) == recovery
    with pytest.raises(WorkspaceError, match="Task branch"):
        manager.restore(recovery.as_dict())

    (recovery.worktree_path / "resume.txt").write_text("keep me\n", encoding="utf-8")
    reused = manager.prepare_recovery(source, snapshot, failure_number=1)
    assert reused == recovery
    assert (reused.worktree_path / "resume.txt").read_text(encoding="utf-8") == "keep me\n"


def test_prepare_recovery_rejects_rewritten_target_history(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    source = manager.prepare(
        repo,
        task_id="task-recovery222222222222222222222222",
        run_number=1,
        requested_mode="main",
        execution_settings={
            "auto_workspace_policy": "always-main",
            "allow_concurrent_main_tasks": True,
        },
        main_running=False,
    )
    (source.worktree_path / "feature.txt").write_text("task result\n", encoding="utf-8")
    snapshot = manager.snapshot_result(source)

    empty_tree = _git(repo, "mktree")
    rewritten = _git(repo, "commit-tree", empty_tree, "-m", "rewritten target")
    _git(repo, "reset", "--hard", rewritten)

    with pytest.raises(WorkspaceError, match="target history"):
        manager.prepare_recovery(source, snapshot, failure_number=1)


def test_snapshot_excludes_only_explicit_run_owned_runtime_path(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    prepared = manager.prepare(
        repo,
        task_id="task-88888888888888888888888888888888",
        run_number=1,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )
    runtime = prepared.project_root / ".ai-task-runner" / "task-runs" / "run-1"
    runtime.mkdir(parents=True)
    (runtime / "state.json").write_text('{"completed": true}\n', encoding="utf-8")
    (prepared.worktree_path / ".github").mkdir()
    (prepared.worktree_path / ".github" / "task.yml").write_text("name: task\n", encoding="utf-8")

    snapshot = manager.snapshot_result(prepared, excluded_paths=(runtime,))

    assert snapshot.no_changes is False
    assert snapshot.created_commit is True
    changed = set(_git(prepared.worktree_path, "show", "--pretty=", "--name-only", "HEAD").splitlines())
    assert ".github/task.yml" in changed
    assert not any(".ai-task-runner" in path for path in changed)
    assert (runtime / "state.json").is_file()


def test_snapshot_rejects_exclude_path_outside_task_worktree(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    prepared = manager.prepare(
        repo,
        task_id="task-99999999999999999999999999999999",
        run_number=1,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )
    (prepared.worktree_path / "change.txt").write_text("change\n", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="outside Task worktree"):
        manager.snapshot_result(prepared, excluded_paths=(tmp_path / "outside",))


def test_explicit_cleanup_removes_only_owned_worktree_and_branch(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    prepared = manager.prepare(
        repo,
        task_id="task-" + "c" * 32,
        run_number=1,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )
    source_project = prepared.source_project_root
    (prepared.worktree_path / "discard.txt").write_text("explicit cleanup\n", encoding="utf-8")
    assert prepared.worktree_path.is_dir()

    result = manager.cleanup(prepared)

    assert result.status == "cleaned"
    assert result.worktree_path == prepared.worktree_path
    assert not prepared.worktree_path.exists()
    branch = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{prepared.task_branch}"],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    assert branch.returncode != 0
    assert source_project.is_dir()

    repeated = manager.cleanup(prepared)
    assert repeated.status == "already_cleaned"


def test_cleanup_rejects_tampered_recovery_identity(tmp_path: Path):
    repo = _repo(tmp_path)
    manager = WorkspaceManager()
    prepared = manager.prepare(
        repo,
        task_id="task-" + "d" * 32,
        run_number=1,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "always-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )
    tampered = prepared.as_dict()
    tampered["task_branch"] = "user/not-owned"

    with pytest.raises(WorkspaceError, match="Task branch"):
        manager.cleanup(tampered)
