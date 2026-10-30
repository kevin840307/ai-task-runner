from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from workspace.merge_queue import MergeQueue
from workspace.model import WorkspaceError


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Merge Queue Test")
    _git(repo, "config", "user.email", "merge-queue@example.invalid")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "base")
    return repo


def test_merge_queue_requires_target_branch(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(WorkspaceError, match="target branch is required"):
        MergeQueue(repo, " ")


def test_merge_queue_fifo_transaction_complete_and_release_contract(tmp_path):
    repo = _repo(tmp_path)
    queue = MergeQueue(repo, "main")

    first, first_is_head = queue.enqueue(
        task_id="task-a",
        run_number=1,
        source_sha="source-a",
        source_base_sha="base-a",
    )
    second, second_is_head = queue.enqueue(
        task_id="task-b",
        run_number=2,
        source_sha="source-b",
        source_base_sha="base-b",
    )

    assert first.seq == 1
    assert second.seq == 2
    assert first_is_head is True
    assert second_is_head is False
    assert queue.transaction(first) is None

    queue.begin_transaction(
        first,
        target_worktree=repo,
        target_head_sha="target-head",
        source_sha="source-a",
    )
    assert queue.transaction(first) == {
        "target_worktree": str(repo.resolve()),
        "target_head_sha": "target-head",
        "source_sha": "source-a",
    }

    assert queue.clear_transaction(first) is True
    assert queue.clear_transaction(first) is False

    with pytest.raises(WorkspaceError, match="head changed"):
        queue.transaction(second)
    with pytest.raises(WorkspaceError, match="non-head"):
        queue.complete(second)

    queue.complete(first)
    assert queue.transaction(second) is None
    assert queue.release_head(task_id="task-b", run_number=2) is True
    assert queue.release_head(task_id="task-b", run_number=2) is False


def test_merge_queue_reenqueue_is_idempotent_and_source_update_clears_transaction(
    tmp_path,
):
    repo = _repo(tmp_path)
    queue = MergeQueue(repo, "main")

    original, is_head = queue.enqueue(
        task_id="task-a",
        run_number=1,
        source_sha="source-a",
        source_base_sha="base-a",
    )
    assert is_head is True

    queue.begin_transaction(
        original,
        target_worktree=repo,
        target_head_sha="target-head",
        source_sha="source-a",
    )
    repeated, repeated_is_head = queue.enqueue(
        task_id="task-a",
        run_number=1,
        source_sha="source-a",
        source_base_sha="base-a",
    )
    assert repeated == original
    assert repeated_is_head is True
    assert queue.transaction(repeated) is not None

    updated, updated_is_head = queue.enqueue(
        task_id="task-a",
        run_number=1,
        source_sha="source-a2",
        source_base_sha="base-a2",
    )
    assert updated.seq == original.seq
    assert updated.source_sha == "source-a2"
    assert updated.source_base_sha == "base-a2"
    assert updated_is_head is True
    assert queue.transaction(updated) is None

    with pytest.raises(WorkspaceError, match="source no longer matches"):
        queue.begin_transaction(
            updated,
            target_worktree=repo,
            target_head_sha="target-head",
            source_sha="old-source",
        )


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"version": 999}, "Unsupported merge queue state version"),
        (
            {
                "version": 1,
                "target_branch": "other",
                "next_seq": 1,
                "entries": [],
            },
            "target branch does not match",
        ),
        (
            {
                "version": 1,
                "target_branch": "main",
                "next_seq": 0,
                "entries": [],
            },
            "state is invalid",
        ),
        (
            {
                "version": 1,
                "target_branch": "main",
                "next_seq": 2,
                "entries": [{
                    "seq": 1,
                    "task_id": "task-a",
                    "run_number": 1,
                    "source_sha": "source-a",
                    "source_base_sha": "base-a",
                    "transaction": {
                        "target_worktree": "",
                        "target_head_sha": "target",
                        "source_sha": "source-a",
                    },
                }],
            },
            "invalid transaction",
        ),
    ],
)
def test_merge_queue_rejects_corrupt_or_mismatched_durable_state(
    tmp_path,
    payload,
    message,
):
    repo = _repo(tmp_path)
    queue = MergeQueue(repo, "main")
    queue.path.parent.mkdir(parents=True, exist_ok=True)
    queue.path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WorkspaceError, match=message):
        queue.enqueue(
            task_id="task-new",
            run_number=1,
            source_sha="source-new",
            source_base_sha="base-new",
        )


def test_merge_queue_rejects_malformed_json(tmp_path):
    repo = _repo(tmp_path)
    queue = MergeQueue(repo, "main")
    queue.path.parent.mkdir(parents=True, exist_ok=True)
    queue.path.write_text("{broken", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="state is invalid"):
        queue.enqueue(
            task_id="task-a",
            run_number=1,
            source_sha="source-a",
            source_base_sha="base-a",
        )
