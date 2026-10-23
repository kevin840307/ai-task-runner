from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from workspace import MergeManager, WorkspaceError, WorkspaceManager


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "merge-test@example.invalid")
    _git(repo, "config", "user.name", "Merge Test")
    (repo / "app.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "feature/base")
    return repo


def _task(repo: Path, suffix: str = "a"):
    manager = WorkspaceManager()
    prepared = manager.prepare(
        repo,
        task_id=f"task-{suffix * 32}",
        run_number=1,
        requested_mode="main",
        execution_settings={
            "auto_workspace_policy": "always-main",
            "allow_concurrent_main_tasks": True,
        },
        main_running=False,
    )
    return manager, prepared


def _snapshot_with_file(repo: Path, suffix: str = "a"):
    manager, prepared = _task(repo, suffix)
    (prepared.worktree_path / "task.txt").write_text(f"task {suffix}\n", encoding="utf-8")
    snapshot = manager.snapshot_result(prepared)
    assert snapshot.no_changes is False
    return manager, prepared, snapshot


def test_direct_merge_uses_no_ff_boundary_without_redundant_validation(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    called = []

    result = MergeManager().merge(
        prepared,
        snapshot,
        validate=lambda _project: called.append(True) or "PASS",
    )

    assert result.status == "merged"
    assert result.validation_required is False
    assert called == []
    assert (repo / "task.txt").read_text(encoding="utf-8") == "task a\n"
    parents = _git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()
    assert len(parents) == 3
    assert snapshot.task_snapshot_sha in parents[1:]


def test_advanced_target_requires_validation_before_merge_commit(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    (repo / "target.txt").write_text("new target\n", encoding="utf-8")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "advance target")
    before = _git(repo, "rev-parse", "HEAD")
    seen = []

    def validate(project: Path) -> str:
        seen.append(project)
        assert (project / "task.txt").read_text(encoding="utf-8") == "task a\n"
        assert (project / "target.txt").read_text(encoding="utf-8") == "new target\n"
        return "PASS"

    result = MergeManager().merge(prepared, snapshot, validate=validate)

    assert result.status == "merged"
    assert result.validation_required is True
    assert result.verdict == "PASS"
    assert seen == [repo.resolve()]
    assert result.target_head_sha == before
    assert result.merged_target_head_sha != before
    assert _git(repo, "status", "--porcelain") == ""


def test_advanced_target_without_validation_aborts_cleanly(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    (repo / "target.txt").write_text("target\n", encoding="utf-8")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "advance target")
    before = _git(repo, "rev-parse", "HEAD")

    result = MergeManager().merge(prepared, snapshot)

    assert result.status == "validation_required"
    assert result.validation_required is True
    assert _git(repo, "rev-parse", "HEAD") == before
    assert _git(repo, "status", "--porcelain") == ""
    merge_head = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    assert merge_head.returncode != 0


@pytest.mark.parametrize(
    ("verdict", "status", "real_failure"),
    [
        ("SOURCE_FAIL", "source_fail", True),
        ("TECHNICAL_ERROR", "technical_error", False),
    ],
)
def test_merge_validation_verdicts_abort_without_mixing_target(
    tmp_path: Path,
    verdict: str,
    status: str,
    real_failure: bool,
):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    (repo / "target.txt").write_text("target\n", encoding="utf-8")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "advance target")
    before = _git(repo, "rev-parse", "HEAD")

    result = MergeManager().merge(prepared, snapshot, validate=lambda _project: verdict)

    assert result.status == status
    assert result.verdict == verdict
    assert result.real_merge_failure is real_failure
    assert _git(repo, "rev-parse", "HEAD") == before
    assert _git(repo, "status", "--porcelain") == ""


def test_validation_exception_is_technical_error_and_does_not_count_merge_failure(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    (repo / "target.txt").write_text("target\n", encoding="utf-8")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "advance target")
    before = _git(repo, "rev-parse", "HEAD")

    def fail(_project: Path) -> str:
        raise RuntimeError("validator unavailable")

    result = MergeManager().merge(prepared, snapshot, validate=fail)

    assert result.status == "technical_error"
    assert result.verdict == "TECHNICAL_ERROR"
    assert result.real_merge_failure is False
    assert "validator unavailable" in result.detail
    assert _git(repo, "rev-parse", "HEAD") == before
    assert _git(repo, "status", "--porcelain") == ""


def test_real_git_conflict_aborts_and_reports_conflicting_files(tmp_path: Path):
    repo = _repo(tmp_path)
    manager, prepared = _task(repo)
    (prepared.worktree_path / "app.txt").write_text("task side\n", encoding="utf-8")
    snapshot = manager.snapshot_result(prepared)
    (repo / "app.txt").write_text("target side\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "target side")
    before = _git(repo, "rev-parse", "HEAD")

    result = MergeManager().merge(prepared, snapshot, validate=lambda _project: "PASS")

    assert result.status == "conflict"
    assert result.real_merge_failure is True
    assert result.conflict_files == ("app.txt",)
    assert _git(repo, "rev-parse", "HEAD") == before
    assert (repo / "app.txt").read_text(encoding="utf-8") == "target side\n"
    assert _git(repo, "status", "--porcelain") == ""


def test_runner_runtime_state_does_not_make_target_dirty_but_policy_file_still_does(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)

    runtime_state = repo / ".ai-task-runner" / "ui"
    runtime_state.mkdir(parents=True)
    (runtime_state / "tasks.json").write_text('{"tasks": []}\n', encoding="utf-8")

    delivered = MergeManager().merge(prepared, snapshot)
    assert delivered.status == "merged"
    assert (repo / "task.txt").read_text(encoding="utf-8") == "task a\n"

    _, prepared_b, snapshot_b = _snapshot_with_file(repo, "b")
    (repo / ".ai-task-runner.yaml").write_text("protected_paths: []\n", encoding="utf-8")
    blocked = MergeManager().merge(prepared_b, snapshot_b)
    assert blocked.status == "waiting_target_clean"
    assert (repo / ".ai-task-runner.yaml").read_text(encoding="utf-8") == "protected_paths: []\n"


def test_dirty_captured_target_checkout_waits_without_stash_or_reset(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    (repo / "user.txt").write_text("uncommitted user work\n", encoding="utf-8")
    before = _git(repo, "rev-parse", "HEAD")

    result = MergeManager().merge(prepared, snapshot)

    assert result.status == "waiting_target_clean"
    assert _git(repo, "rev-parse", "HEAD") == before
    assert (repo / "user.txt").read_text(encoding="utf-8") == "uncommitted user work\n"


def test_target_branch_not_checked_out_uses_managed_delivery_without_switching_user_checkout(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    _git(repo, "checkout", "-b", "user/other")
    assert _git(repo, "branch", "--show-current") == "user/other"

    result = MergeManager().merge(prepared, snapshot)

    assert result.status == "merged"
    assert _git(repo, "branch", "--show-current") == "user/other"
    assert _git(repo, "show", "feature/base:task.txt") == "task a"
    managed = prepared.worktree_path.parent / "_delivery"
    assert not any(managed.glob("*")) if managed.exists() else True


def test_target_branch_in_unmanaged_worktree_waits_without_mutation(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    _git(repo, "checkout", "-b", "user/other")
    user_target = tmp_path / "user-target"
    _git(repo, "worktree", "add", str(user_target), "feature/base")
    before = _git(user_target, "rev-parse", "HEAD")

    result = MergeManager().merge(prepared, snapshot)

    assert result.status == "waiting_target_workspace"
    assert result.target_worktree == user_target.resolve()
    assert _git(user_target, "rev-parse", "HEAD") == before
    assert _git(user_target, "status", "--porcelain") == ""


def test_deleted_target_branch_waits_without_guessing_replacement(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    _git(repo, "checkout", "-b", "user/other")
    _git(repo, "branch", "-D", "feature/base")

    result = MergeManager().merge(prepared, snapshot)

    assert result.status == "waiting_target_branch"
    assert _git(repo, "branch", "--show-current") == "user/other"


def test_rewritten_target_history_waits_without_merge_failure(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    empty_tree = _git(repo, "mktree")
    rewritten = _git(repo, "commit-tree", empty_tree, "-m", "rewritten target")
    _git(repo, "reset", "--hard", rewritten)

    result = MergeManager().merge(prepared, snapshot)

    assert result.status == "waiting_target_history"
    assert result.real_merge_failure is False
    assert _git(repo, "rev-parse", "HEAD") == rewritten


def test_already_merged_source_finalizes_idempotently_without_duplicate_merge(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    _git(repo, "merge", "--no-ff", prepared.task_branch, "-m", "manual delivery")
    before = _git(repo, "rev-parse", "HEAD")
    count = _git(repo, "rev-list", "--count", "HEAD")

    result = MergeManager().merge(prepared, snapshot, validate=lambda _project: "SOURCE_FAIL")

    assert result.status == "merged"
    assert result.merged_target_head_sha == before
    assert _git(repo, "rev-list", "--count", "HEAD") == count


def test_restart_does_not_abort_unowned_same_source_merge(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    before = _git(repo, "rev-parse", "HEAD")
    _git(repo, "merge", "--no-ff", "--no-commit", prepared.task_branch)
    assert _git(repo, "rev-parse", "MERGE_HEAD") == snapshot.task_snapshot_sha

    result = MergeManager().merge(prepared, snapshot)

    assert result.status == "waiting_target_workspace"
    assert _git(repo, "rev-parse", "HEAD") == before
    assert _git(repo, "rev-parse", "MERGE_HEAD") == snapshot.task_snapshot_sha
    _git(repo, "merge", "--abort")
    assert _git(repo, "status", "--porcelain") == ""


def test_restart_reconciles_owned_unfinished_merge_in_project_checkout(tmp_path: Path):
    repo = _repo(tmp_path)
    _, prepared, snapshot = _snapshot_with_file(repo)
    (repo / "target.txt").write_text("advanced target\n", encoding="utf-8")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "advance target")
    target_head = _git(repo, "rev-parse", "HEAD")

    def crash_during_validation(_project: Path) -> str:
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        MergeManager().merge(
            prepared,
            snapshot,
            validate=crash_during_validation,
        )

    assert _git(repo, "rev-parse", "HEAD") == target_head
    assert _git(repo, "rev-parse", "MERGE_HEAD") == snapshot.task_snapshot_sha

    restarted = MergeManager().merge(
        prepared,
        snapshot,
        validate=lambda _project: "PASS",
    )

    assert restarted.status == "merged"
    assert restarted.merge_queue_seq == 1
    assert restarted.target_head_sha == target_head
    assert (repo / "task.txt").read_text(encoding="utf-8") == "task a\n"
    assert (repo / "target.txt").read_text(encoding="utf-8") == "advanced target\n"
    assert _git(repo, "status", "--porcelain") == ""
    missing_merge_head = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    assert missing_merge_head.returncode != 0


def test_source_branch_change_after_snapshot_fails_closed(tmp_path: Path):
    repo = _repo(tmp_path)
    manager, prepared, snapshot = _snapshot_with_file(repo)
    (prepared.worktree_path / "late.txt").write_text("late\n", encoding="utf-8")
    manager.snapshot_result(prepared)

    with pytest.raises(WorkspaceError, match="snapshot no longer matches"):
        MergeManager().merge(prepared, snapshot)


def test_concurrent_main_merge_queue_is_durable_fifo_and_prevents_overtake(tmp_path: Path):
    repo = _repo(tmp_path)
    manager_a, prepared_a = _task(repo, "a")
    manager_b, prepared_b = _task(repo, "b")

    (prepared_a.worktree_path / "app.txt").write_text("task a side\n", encoding="utf-8")
    snapshot_a = manager_a.snapshot_result(prepared_a)
    (prepared_b.worktree_path / "b.txt").write_text("task b\n", encoding="utf-8")
    snapshot_b = manager_b.snapshot_result(prepared_b)

    (repo / "app.txt").write_text("target side\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "advance target with conflict")

    blocked_head = MergeManager().merge(prepared_a, snapshot_a, validate=lambda _project: "PASS")
    assert blocked_head.status == "conflict"
    assert blocked_head.merge_queue_seq == 1

    waiting_b = MergeManager().merge(prepared_b, snapshot_b, validate=lambda _project: "PASS")
    assert waiting_b.status == "pending_merge"
    assert waiting_b.merge_queue_seq == 2
    assert not (repo / "b.txt").exists()

    restarted_b = MergeManager().merge(prepared_b, snapshot_b, validate=lambda _project: "PASS")
    assert restarted_b.status == "pending_merge"
    assert restarted_b.merge_queue_seq == 2

    _git(repo, "merge", "--no-ff", "-s", "ours", prepared_a.task_branch, "-m", "external delivery a")
    finalized_a = MergeManager().merge(prepared_a, snapshot_a, validate=lambda _project: "SOURCE_FAIL")
    assert finalized_a.status == "merged"
    assert finalized_a.merge_queue_seq == 1

    delivered_b = MergeManager().merge(prepared_b, snapshot_b, validate=lambda _project: "PASS")
    assert delivered_b.status == "merged"
    assert delivered_b.merge_queue_seq == 2
    assert (repo / "b.txt").read_text(encoding="utf-8") == "task b\n"


def test_failed_queue_head_can_be_released_for_fallback_without_blocking_next_task(tmp_path: Path):
    repo = _repo(tmp_path)
    manager_a, prepared_a = _task(repo, "a")
    manager_b, prepared_b = _task(repo, "b")

    (prepared_a.worktree_path / "app.txt").write_text("task a side\n", encoding="utf-8")
    snapshot_a = manager_a.snapshot_result(prepared_a)
    (prepared_b.worktree_path / "b.txt").write_text("task b\n", encoding="utf-8")
    snapshot_b = manager_b.snapshot_result(prepared_b)

    (repo / "app.txt").write_text("target side\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "advance target with conflict")

    blocked = MergeManager().merge(prepared_a, snapshot_a, validate=lambda _project: "PASS")
    waiting = MergeManager().merge(prepared_b, snapshot_b, validate=lambda _project: "PASS")
    assert blocked.status == "conflict"
    assert waiting.status == "pending_merge"

    manager = MergeManager()
    assert manager.release_merge_slot(prepared_a, snapshot_a) is True
    assert manager.release_merge_slot(prepared_a, snapshot_a) is False

    delivered = manager.merge(prepared_b, snapshot_b, validate=lambda _project: "PASS")
    assert delivered.status == "merged"
    assert (repo / "b.txt").read_text(encoding="utf-8") == "task b\n"


@pytest.mark.parametrize("task_count", [2, 5, 10])
def test_merge_queue_assigns_stable_fifo_sequence_to_concurrent_main_tasks(
    tmp_path: Path,
    task_count: int,
):
    repo = _repo(tmp_path)
    prepared = []
    suffixes = tuple(chr(ord("a") + index) for index in range(task_count))
    for index, suffix in enumerate(suffixes, start=1):
        manager, workspace = _task(repo, suffix)
        if index == 1:
            (workspace.worktree_path / "app.txt").write_text("queue head\n", encoding="utf-8")
        else:
            (workspace.worktree_path / f"{suffix}.txt").write_text(f"{suffix}\n", encoding="utf-8")
        prepared.append((workspace, manager.snapshot_result(workspace)))

    assert len({workspace.worktree_path for workspace, _snapshot in prepared}) == task_count
    assert len({workspace.task_branch for workspace, _snapshot in prepared}) == task_count

    (repo / "app.txt").write_text("target conflict\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "block queue head")

    first = MergeManager().merge(*prepared[0], validate=lambda _project: "PASS")
    assert first.status == "conflict"
    assert first.merge_queue_seq == 1

    for expected_seq, (workspace, snapshot) in enumerate(prepared[1:], start=2):
        # A fresh manager models another process/restart reading the durable FIFO.
        result = MergeManager().merge(workspace, snapshot, validate=lambda _project: "PASS")
        assert result.status == "pending_merge"
        assert result.merge_queue_seq == expected_seq
