from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from runner.agent import opencode as opencode_module
from runner.agent import qwen as qwen_module
from runner.agent.backend import BackendError
from runner.runtime.process_runner import ProcessResult
from runner.workflow.loader import normalize_workflow
from runner.workflow.registry import create_stage
from runner.workflow.results import decode_tasks
from workspace import PublishManager, WorkspaceError, WorkspaceManager
from workspace import worktree as worktree_module


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Code Derived Gap Test")
    _git(repo, "config", "user.email", "gap-test@example.invalid")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "base")
    return repo


def _publish_fixture(tmp_path: Path):
    repo = _repo(tmp_path)
    remote = tmp_path / "origin.git"
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


def test_repository_git_lock_heartbeat_prevents_live_owner_from_being_stolen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(worktree_module, "STALE_LOCK_SECONDS", 0.08)
    monkeypatch.setattr(worktree_module, "LOCK_POLL_SECONDS", 0.01)
    monkeypatch.setattr(worktree_module, "LOCK_TIMEOUT_SECONDS", 0.18)

    with worktree_module.repository_git_lock(repo):
        with pytest.raises(WorkspaceError, match="Timed out waiting for Git lock"):
            with worktree_module.repository_git_lock(repo):
                pytest.fail("a live repository lock must never be stolen as stale")


def test_git_lock_old_owner_does_not_unlink_replacement_lock(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    common = worktree_module.repository_identity(repo)
    filename = "replacement-owner-test.lock"
    lock = common / filename

    with worktree_module._git_file_lock(repo, filename):
        if os.name == "nt":
            # Windows does not allow unlinking an open lock file. Changing the
            # ownership token still proves that the old owner must not remove a
            # lock it no longer owns.
            lock.write_text("replacement-owner\n", encoding="ascii")
        else:
            # POSIX allows a new inode to replace the path while the old owner
            # still holds its original file descriptor.
            lock.unlink()
            lock.write_text("replacement-owner\n", encoding="ascii")

    assert lock.read_text(encoding="ascii") == "replacement-owner\n"
    lock.unlink()


def test_publish_reports_remote_unavailable_without_mutating_result(tmp_path: Path) -> None:
    repo, _remote, prepared, snapshot = _publish_fixture(tmp_path)
    _git(repo, "remote", "remove", "origin")

    result = PublishManager().publish(
        prepared,
        branch=prepared.task_branch,
        expected_sha=snapshot.task_snapshot_sha,
    )

    assert result.status == "remote_unavailable"
    assert result.branch == prepared.task_branch
    assert result.sha == snapshot.task_snapshot_sha


def test_publish_reports_non_fast_forward_rejection(tmp_path: Path) -> None:
    repo, _remote, prepared, snapshot = _publish_fixture(tmp_path)

    (repo / "remote-only.txt").write_text("remote divergence\n", encoding="utf-8")
    _git(repo, "add", "remote-only.txt")
    _git(repo, "commit", "-m", "remote divergent commit")
    _git(repo, "push", "origin", f"HEAD:refs/heads/{prepared.task_branch}")

    result = PublishManager().publish(
        prepared,
        branch=prepared.task_branch,
        expected_sha=snapshot.task_snapshot_sha,
    )

    assert result.status == "rejected"
    assert result.branch == prepared.task_branch
    assert result.sha == snapshot.task_snapshot_sha
    assert result.detail


class _Response:
    def __init__(self, body: bytes, *, status: int = 200, close_error: bool = False) -> None:
        self._body = body
        self.status = status
        self._close_error = close_error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        if self._close_error:
            raise OSError("close failed")


def test_qwen_daemon_http_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        qwen_module.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _Response(b"{not-json"),
    )
    with pytest.raises(BackendError, match="returned invalid JSON"):
        qwen_module._qwen_http_json_response("http://127.0.0.1:4170", "/capabilities")


def test_qwen_daemon_http_surfaces_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        qwen_module,
        "_qwen_http_json_response",
        lambda *args, **kwargs: (503, {"message": "temporarily unavailable"}),
    )
    with pytest.raises(BackendError, match=r"HTTP 503.*temporarily unavailable"):
        qwen_module._qwen_http_json("http://127.0.0.1:4170", "/capabilities")


def test_qwen_sse_rejects_invalid_json() -> None:
    with pytest.raises(BackendError, match="event stream returned invalid JSON"):
        list(qwen_module._qwen_sse_events([b"data: not-json\n"]))


def test_qwen_sse_enforces_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qwen_module.time, "monotonic", lambda: 10.0)
    with pytest.raises(BackendError, match="turn timed out"):
        list(qwen_module._qwen_sse_events([b"data: {}\n"], deadline=5.0))


def test_qwen_sse_stream_closes_response_even_when_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _Response(b"", close_error=True)
    monkeypatch.setattr(qwen_module.urllib.request, "urlopen", lambda *args, **kwargs: response)

    with qwen_module._qwen_sse_stream("http://127.0.0.1:4170", "session-1") as stream:
        assert stream is response


def test_opencode_api_accepts_json_payload_after_non_json_banner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opencode_module,
        "run_process",
        lambda *args, **kwargs: ProcessResult(
            'OpenCode banner\n{"data":[{"name":"review"}]}\n',
            0,
        ),
    )
    assert opencode_module._opencode_api_request(tmp_path, "command.list") == [
        {"name": "review"}
    ]


def test_opencode_api_rejects_unparseable_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opencode_module,
        "run_process",
        lambda *args, **kwargs: ProcessResult("not-json\nstill-not-json\n", 0),
    )
    with pytest.raises(BackendError, match="returned invalid JSON"):
        opencode_module._opencode_api_request(tmp_path, "command.list")


def test_opencode_api_wraps_process_start_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise OSError("process unavailable")

    monkeypatch.setattr(opencode_module, "run_process", fail)
    with pytest.raises(BackendError, match="process unavailable"):
        opencode_module._opencode_api_request(tmp_path, "command.list")


@pytest.mark.parametrize(
    ("workflow", "message"),
    [
        (
            {"stages": {"execute": {"type": "base"}}, "flow": ["execute"], "extra": True},
            "unknown keys",
        ),
        (
            {"stages": {"execute": {"type": "base"}}, "flow": ["missing"]},
            "unknown workflow stage",
        ),
        (
            {
                "stages": {
                    "execute": {
                        "type": "base",
                        "instructions_file": "missing-instructions.md",
                    }
                },
                "flow": ["execute"],
            },
            "instructions not found",
        ),
    ],
)
def test_workflow_loader_fails_closed_on_invalid_contract(
    tmp_path: Path,
    workflow: dict,
    message: str,
) -> None:
    with pytest.raises(Exception, match=message):
        normalize_workflow(workflow, tmp_path / "workflow.yaml")


def test_stage_factory_rejects_unknown_stage_type() -> None:
    with pytest.raises(Exception, match="unknown workflow Stage type"):
        create_stage({"name": "mystery", "type": "does-not-exist"})


def test_task_decoder_rejects_duplicate_task_ids() -> None:
    task = {
        "id": "duplicate",
        "title": "Task",
        "description": "Description",
        "deliverable": "Result",
        "acceptance_criteria": ["Pass"],
    }
    with pytest.raises(Exception, match="ids must be unique"):
        decode_tasks([task, dict(task)], cycle=1)
