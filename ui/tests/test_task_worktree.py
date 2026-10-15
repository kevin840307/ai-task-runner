from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ui import task_worktree as worktree


def completed(command, stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess(command, code, stdout, stderr)


def test_list_worktrees_parses_main_and_secondary(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    secondary = tmp_path / "repo-worktrees" / "task"
    secondary.mkdir(parents=True)

    def fake_git(root, args, check=True):
        if args == ["rev-parse", "--show-toplevel"]:
            return completed(args, str(repo))
        if args == ["worktree", "list", "--porcelain"]:
            return completed(args, (
                f"worktree {repo}\nHEAD abc\nbranch refs/heads/main\n\n"
                f"worktree {secondary}\nHEAD def\nbranch refs/heads/ai/task-x\n\n"
            ))
        raise AssertionError(args)

    monkeypatch.setattr(worktree, "_git", fake_git)
    rows = worktree.list_worktrees(repo)

    assert rows[0]["is_main"] is True
    assert rows[0]["branch"] == "main"
    assert rows[1]["is_main"] is False
    assert rows[1]["branch"] == "ai/task-x"


def test_create_task_worktree_uses_unique_task_branch_and_head(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    calls = []

    monkeypatch.setattr(worktree, "git_root", lambda value: repo)
    monkeypatch.setattr(worktree, "list_worktrees", lambda value: [{"path": str(repo), "branch": "main", "is_main": True}])
    monkeypatch.setattr(
        worktree,
        "_git",
        lambda root, args, check=True: calls.append(args) or completed(args),
    )

    result = worktree.create_task_worktree(repo, "abcdef0123456789abcdef0123456789")

    assert result["branch"] == "ai/task-abcdef0123456789"
    assert result["managed"] is True
    assert calls == [[
        "worktree", "add", "-b", "ai/task-abcdef0123456789",
        str(Path(result["path"])), "HEAD",
    ]]


def test_remove_worktree_never_forces_or_deletes_branch(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    secondary = tmp_path / "wt"
    secondary.mkdir()
    calls = []
    monkeypatch.setattr(worktree, "git_root", lambda value: repo)
    monkeypatch.setattr(worktree, "list_worktrees", lambda value: [
        {"path": str(repo), "branch": "main", "is_main": True},
        {"path": str(secondary), "branch": "ai/task-x", "is_main": False},
    ])
    monkeypatch.setattr(
        worktree,
        "_git",
        lambda root, args, check=True: calls.append(args) or completed(args),
    )

    worktree.remove_task_worktree(repo, secondary)

    assert calls == [["worktree", "remove", str(secondary)]]
    assert "--force" not in calls[0]
    assert all("branch" not in call for call in calls)


def test_attach_rejects_unrelated_path(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(worktree, "git_root", lambda value: repo)
    monkeypatch.setattr(worktree, "list_worktrees", lambda value: [
        {"path": str(repo), "branch": "main", "is_main": True},
    ])
    with pytest.raises(worktree.WorktreeError, match="not a Git worktree"):
        worktree.attach_existing_worktree(repo, str(tmp_path / "other"))


def test_runtime_archive_retry_reuses_existing_evidence_after_source_runtime_removed(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "state.json").write_text('{"completed": true}', encoding="utf-8")

    result = worktree.archive_runtime(wt, archive)

    assert Path(result) == archive
    assert not (wt / ".ai-task-runner").exists()
    assert (archive / "state.json").read_text(encoding="utf-8") == '{"completed": true}'


def test_runtime_archive_is_copy_and_does_not_delete_source(tmp_path):
    wt = tmp_path / "wt"
    runtime = wt / ".ai-task-runner"
    runtime.mkdir(parents=True)
    (runtime / "state.json").write_text('{"completed": true}', encoding="utf-8")
    archive = tmp_path / "repo" / ".ai-task-runner" / "ui" / "task-history" / "t" / "runtime"

    result = worktree.archive_runtime(wt, archive)

    assert Path(result, "state.json").read_text(encoding="utf-8") == '{"completed": true}'
    assert (runtime / "state.json").is_file()
