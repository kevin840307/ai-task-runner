from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ui.task_run_service import TaskRunService
from ui.task_service import TaskService
from workspace import WorkspaceManager


def _git(path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "app.txt").write_text("base\n", encoding="utf-8")
    workflow = repo / "workflow.yaml"
    workflow.write_text("stages: {}\nflow: []\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    return repo


def _task(service: TaskService, repo: Path, *, workspace: str) -> dict:
    return service.create(
        repo,
        {
            "title": "Run me",
            "items": [{
                "title": "One",
                "prompt": "Implement one",
                "workflow": str(repo / "workflow.yaml"),
                "project": str(repo),
                "workspace": workspace,
            }],
        },
        request_id=f"create-{workspace}",
    )


def _service(
    tasks: TaskService,
    repo: Path,
    *,
    runtime: dict,
    launches: list,
    stops: list,
    resumes: list,
    settings: dict | None = None,
) -> TaskRunService:
    def launch(project: Path, goal: str | None, **kwargs):
        launches.append((Path(project), goal, dict(kwargs)))
        (Path(project) / "result.txt").write_text("done\n", encoding="utf-8")

    return TaskRunService(
        tasks,
        execution_settings=lambda: dict(settings or {
            "auto_workspace_policy": "busy-worktree",
            "merge_failure_limit": 3,
            "allow_concurrent_main_tasks": False,
        }),
        preferences=lambda _project: {
            "agent": "qwen",
            "model": "model-a",
            "mode": "auto",
            "reasoning": "high",
        },
        backend_default=lambda _project: "qwen",
        resolve_workflow=lambda _project, selected: Path(selected),
        launch=launch,
        read_runtime=lambda _project: dict(runtime),
        stop_runtime=lambda project: stops.append(Path(project)),
        resume_runtime=lambda project: resumes.append(Path(project)),
        workspace_manager=WorkspaceManager(worktree_root=repo.parent / "worktrees"),
        poll_interval=0.05,
        auto_watch=False,
    )


def test_task_run_worktree_closes_as_worktree_ready_without_touching_project(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="worktree")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    launches, stops, resumes = [], [], []
    service = _service(tasks, repo, runtime=runtime, launches=launches, stops=stops, resumes=resumes)

    started = service.start(repo, created["task_id"], request_id="run-1")
    assert started["status"] == "ongoing"
    assert started["run"]["run_number"] == 1
    assert started["run"]["workspace"]["effective_mode"] == "worktree"
    assert launches[0][0] != repo
    assert not (repo / "result.txt").exists()

    runtime.update({"running": False, "completed": True})
    closed = service.reconcile(repo, created["task_id"])
    assert closed["status"] == "closed"
    assert closed["run"]["phase"] == "worktree_ready"
    assert closed["completed_item_count"] == 1
    assert closed["run"]["workspace_result"]["merge"]["status"] == "worktree_ready"
    assert not (repo / "result.txt").exists()


def test_task_run_main_merges_unchanged_target_and_is_idempotent(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    service = _service(tasks, repo, runtime=runtime, launches=[], stops=[], resumes=[])

    started = service.start(repo, created["task_id"], request_id="main-run")
    assert started["run"]["workspace"]["effective_mode"] == "main"
    duplicate = service.start(repo, created["task_id"], request_id="main-run")
    assert duplicate["run"]["run_number"] == 1

    runtime.update({"running": False, "completed": True})
    closed = service.reconcile(repo, created["task_id"])
    assert closed["status"] == "closed"
    assert closed["run"]["phase"] == "merged"
    assert closed["run"]["workspace_result"]["merge"]["status"] == "merged"
    assert (repo / "result.txt").read_text(encoding="utf-8") == "done\n"
    assert _git(repo, "branch", "--show-current") == "main"


def test_main_no_changes_closes_with_explicit_no_changes_phase(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    service = _service(tasks, repo, runtime=runtime, launches=[], stops=[], resumes=[])

    started = service.start(repo, created["task_id"], request_id="main-no-changes")
    task_root = Path(started["run"]["workspace"]["project_root"])
    (task_root / "result.txt").unlink()
    before_head = _git(repo, "rev-parse", "HEAD")
    before_count = _git(repo, "rev-list", "--count", "HEAD")

    runtime.update({"running": False, "completed": True})
    closed = service.reconcile(repo, created["task_id"])

    assert closed["status"] == "closed"
    assert closed["run"]["phase"] == "no_changes"
    merge = closed["run"]["workspace_result"]["merge"]
    assert merge["status"] == "no_changes"
    assert merge["merged_target_head_sha"] == before_head
    assert _git(repo, "rev-list", "--count", "HEAD") == before_count


def test_restart_finalizes_already_merged_current_source_without_duplicate_commit(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    service = _service(tasks, repo, runtime=runtime, launches=[], stops=[], resumes=[])

    started = service.start(repo, created["task_id"], request_id="restart-merged-source")
    manager = WorkspaceManager(worktree_root=repo.parent / "worktrees")
    prepared = manager.restore(started["run"]["workspace"])
    snapshot = manager.snapshot_result(
        prepared,
        excluded_paths=(prepared.project_root / ".ai-task-runner",),
    )
    tasks.transition_run(
        repo,
        created["task_id"],
        prepared.run_number,
        phase="merging",
        status="ongoing",
        workspace_result={
            "snapshot": snapshot.as_dict(),
            "merge_source": {
                "workspace": prepared.as_dict(),
                "snapshot": snapshot.as_dict(),
            },
            "effective_mode": "main",
            "branch": prepared.task_branch,
            "path": str(prepared.worktree_path),
        },
    )

    _git(repo, "merge", "--no-ff", prepared.task_branch, "-m", "external durable delivery")
    before_head = _git(repo, "rev-parse", "HEAD")
    before_count = _git(repo, "rev-list", "--count", "HEAD")

    restarted = _service(tasks, repo, runtime=runtime, launches=[], stops=[], resumes=[])
    closed = restarted.reconcile(repo, created["task_id"])

    assert closed["status"] == "closed"
    assert closed["run"]["phase"] == "merged"
    merge = closed["run"]["workspace_result"]["merge"]
    assert merge["status"] == "merged"
    assert merge["merged_target_head_sha"] == before_head
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "rev-list", "--count", "HEAD") == before_count


def test_stop_resume_and_service_restart_reuse_same_workspace_identity(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="worktree")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {"stop": True}}
    launches, stops, resumes = [], [], []
    first = _service(tasks, repo, runtime=runtime, launches=launches, stops=stops, resumes=resumes)
    started = first.start(repo, created["task_id"], request_id="run-stable")
    workspace = dict(started["run"]["workspace"])

    first.stop(repo, created["task_id"])
    assert stops == [Path(workspace["project_root"])]
    tasks.transition_run(
        repo,
        created["task_id"],
        1,
        phase="stopped",
        status="paused",
    )

    restarted = _service(tasks, repo, runtime=runtime, launches=launches, stops=stops, resumes=resumes)
    resumed = restarted.resume(repo, created["task_id"])
    assert resumes == [Path(workspace["project_root"])]
    assert resumed["run"]["workspace"] == workspace
    assert resumed["run_count"] == 1


def test_launch_failure_pauses_and_retry_reuses_same_run_workspace(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="worktree")
    calls = []

    def failing_launch(project: Path, goal: str | None, **kwargs):
        calls.append(Path(project))
        if len(calls) == 1:
            raise RuntimeError("launch failed")

    service = TaskRunService(
        tasks,
        execution_settings=lambda: {
            "auto_workspace_policy": "busy-worktree",
            "merge_failure_limit": 3,
            "allow_concurrent_main_tasks": False,
        },
        preferences=lambda _project: {"agent": "qwen", "model": "", "mode": "auto"},
        backend_default=lambda _project: "qwen",
        resolve_workflow=lambda _project, selected: Path(selected),
        launch=failing_launch,
        read_runtime=lambda _project: {"running": True, "launching": False, "completed": False, "actions": {}},
        stop_runtime=lambda _project: None,
        resume_runtime=lambda _project: None,
        workspace_manager=WorkspaceManager(worktree_root=repo.parent / "worktrees"),
        auto_watch=False,
    )

    try:
        service.start(repo, created["task_id"], request_id="launch-fail")
    except RuntimeError:
        pass
    else:
        raise AssertionError("launch failure must propagate")
    paused = tasks.get(repo, created["task_id"])
    assert paused["status"] == "paused"
    assert paused["run"]["phase"] == "launch_failed"
    original_workspace = dict(paused["run"]["workspace"])

    resumed = service.resume(repo, created["task_id"])
    assert resumed["status"] == "ongoing"
    assert resumed["run_count"] == 1
    assert resumed["run"]["workspace"] == original_workspace
    assert calls[0] == calls[1]


def test_main_target_advance_fails_closed_at_validation_required(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    service = _service(tasks, repo, runtime=runtime, launches=[], stops=[], resumes=[])

    service.start(repo, created["task_id"], request_id="advanced-main")
    (repo / "target.txt").write_text("target advanced\n", encoding="utf-8")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "advance target")

    runtime.update({"running": False, "completed": True})
    waiting = service.reconcile(repo, created["task_id"])
    assert waiting["status"] == "ongoing"
    assert waiting["run"]["phase"] == "validation_required"
    assert waiting["run"]["workspace_result"]["merge"]["validation_required"] is True
    assert not (repo / "result.txt").exists()


def test_real_merge_failure_over_limit_falls_back_to_retained_worktree(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    settings = {
        "auto_workspace_policy": "busy-worktree",
        "merge_failure_limit": 0,
        "allow_concurrent_main_tasks": False,
    }
    service = _service(
        tasks,
        repo,
        runtime=runtime,
        launches=[],
        stops=[],
        resumes=[],
        settings=settings,
    )

    started = service.start(repo, created["task_id"], request_id="merge-failure")
    task_root = Path(started["run"]["workspace"]["project_root"])
    (task_root / "app.txt").write_text("task side\n", encoding="utf-8")
    (repo / "app.txt").write_text("target side\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "target side")

    runtime.update({"running": False, "completed": True})
    fallback = service.reconcile(repo, created["task_id"])
    assert fallback["status"] == "closed"
    assert fallback["run"]["phase"] == "worktree_ready"
    assert fallback["merge_failure_count"] == 1
    result = fallback["run"]["workspace_result"]
    assert result["merge"]["status"] == "worktree_ready"
    assert result["merge"]["attempt_status"] == "conflict"
    assert result["delivery_fallback"] == {
        "mode": "isolated_worktree",
        "reason": "merge_failure_limit_exceeded",
    }
    assert result["last_merge_failure"]["source_branch"] == started["run"]["workspace"]["task_branch"]
    assert (repo / "app.txt").read_text(encoding="utf-8") == "target side\n"
    assert (task_root / "app.txt").read_text(encoding="utf-8") == "task side\n"


def test_real_merge_failure_runs_incremental_recovery_and_retries_latest_source(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    launches = []
    service = _service(tasks, repo, runtime=runtime, launches=launches, stops=[], resumes=[])

    started = service.start(repo, created["task_id"], request_id="merge-recovery")
    original_root = Path(started["run"]["workspace"]["project_root"])
    original_branch = started["run"]["workspace"]["task_branch"]
    (original_root / "app.txt").write_text("task side\n", encoding="utf-8")
    (repo / "app.txt").write_text("target side\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "target side")
    latest_target = _git(repo, "rev-parse", "HEAD")

    runtime.update({"running": False, "completed": True})
    recovering = service.reconcile(repo, created["task_id"])
    assert recovering["status"] == "ongoing"
    assert recovering["run"]["phase"] == "conflict_recovery"
    assert recovering["merge_failure_count"] == 1
    recovery = recovering["run"]["workspace_result"]["recovery"]
    recovery_root = Path(recovery["workspace"]["project_root"])
    recovery_branch = recovery["workspace"]["task_branch"]
    assert recovery_branch.startswith(f"local/recovery/{created['task_id']}-r1-f1")
    assert recovery["workspace"]["task_base_sha"] == latest_target
    assert recovery_root != original_root
    assert (original_root / "app.txt").read_text(encoding="utf-8") == "task side\n"
    assert (recovery_root / "app.txt").read_text(encoding="utf-8") == "target side\n"
    assert "task side" in Path(recovery["patch_path"]).read_text(encoding="utf-8")
    assert "Merge-repair task only" in launches[-1][1]
    assert "Original Task base SHA" in launches[-1][1]
    assert "Committed Task snapshot SHA" in launches[-1][1]
    assert "Latest target HEAD" in launches[-1][1]
    assert "app.txt" in launches[-1][1]

    (recovery_root / "app.txt").write_text("integrated task + target\n", encoding="utf-8")
    closed = service.reconcile(repo, created["task_id"])
    assert closed["status"] == "closed"
    assert closed["run"]["phase"] == "merged"
    result = closed["run"]["workspace_result"]
    assert result["merge"]["status"] == "merged"
    assert result["merge_source"]["workspace"]["task_branch"] == recovery_branch
    assert result["merge_source"]["workspace"]["task_branch"] != original_branch
    assert (repo / "app.txt").read_text(encoding="utf-8") == "integrated task + target\n"
    assert (original_root / "app.txt").read_text(encoding="utf-8") == "task side\n"


def test_task_run_request_is_durable_and_idempotent(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="worktree")
    workspace = {
        "task_id": created["task_id"],
        "run_number": 1,
        "project_root": str(repo.parent / "worktrees" / "x"),
    }
    first = tasks.begin_run(repo, created["task_id"], request_id="req-1", workspace=workspace)
    duplicate = tasks.begin_run(repo, created["task_id"], request_id="req-1", workspace=workspace)
    assert first["duplicate"] is False
    assert duplicate["duplicate"] is True
    raw = json.loads(tasks._state_path(repo).read_text(encoding="utf-8"))
    assert raw["run_requests"]["req-1"]["run_number"] == 1


def test_retry_same_run_request_does_not_prepare_second_workspace(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    launches = []
    service = _service(tasks, repo, runtime=runtime, launches=launches, stops=[], resumes=[])

    first = service.start(repo, created["task_id"], request_id="stable-start")
    second = service.start(repo, created["task_id"], request_id="stable-start")

    assert first["run"]["run_number"] == 1
    assert second["run"]["run_number"] == 1
    assert second["run"]["workspace"] == first["run"]["workspace"]
    assert len(launches) == 1
    branches = _git(repo, "branch", "--format=%(refname:short)").splitlines()
    assert [name for name in branches if name.startswith("local/task/")] == [
        first["run"]["workspace"]["task_branch"]
    ]


def test_reconcile_reuses_persisted_snapshot_instead_of_turning_pending_delivery_into_no_changes(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    service = _service(tasks, repo, runtime=runtime, launches=[], stops=[], resumes=[])

    service.start(repo, created["task_id"], request_id="stable-snapshot")
    (repo / "target.txt").write_text("target advanced\n", encoding="utf-8")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "advance target")

    runtime.update({"running": False, "completed": True})
    first = service.reconcile(repo, created["task_id"])
    assert first["run"]["phase"] == "validation_required"
    first_snapshot = dict(first["run"]["workspace_result"]["snapshot"])
    assert first_snapshot["no_changes"] is False

    second = service.reconcile(repo, created["task_id"])
    assert second["status"] == "ongoing"
    assert second["run"]["phase"] == "validation_required"
    assert second["run"]["workspace_result"]["snapshot"] == first_snapshot
    assert second["run"]["workspace_result"]["merge"]["status"] == "validation_required"
    assert not (repo / "result.txt").exists()
