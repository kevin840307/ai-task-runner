from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from ui.task_run_service import TaskRunService
from ui.task_service import TaskService
from workspace import PublishResult, WorkspaceManager


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


def _task(
    service: TaskService,
    repo: Path,
    *,
    workspace: str,
    request_id: str | None = None,
    title: str = "Run me",
) -> dict:
    return service.create(
        repo,
        {
            "title": title,
            "items": [{
                "title": "One",
                "prompt": "Implement one",
                "workflow": str(repo / "workflow.yaml"),
                "project": str(repo),
                "workspace": workspace,
            }],
        },
        request_id=request_id or f"create-{workspace}",
    )


def _task_list(
    service: TaskService,
    repo: Path,
    *,
    workspaces: tuple[str, ...] = ("worktree", "worktree"),
) -> dict:
    return service.create(
        repo,
        {
            "title": "Ordered list",
            "items": [
                {
                    "title": f"Item {index + 1}",
                    "prompt": f"Implement item {index + 1}",
                    "workflow": str(repo / "workflow.yaml"),
                    "project": str(repo),
                    "workspace": workspace,
                }
                for index, workspace in enumerate(workspaces)
            ],
        },
        request_id="create-list-" + "-".join(workspaces),
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
    merge_validator=None,
    publish_manager=None,
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
            "workflow": str(repo / "workflow.yaml"),
        },
        backend_default=lambda _project: "qwen",
        resolve_workflow=lambda _project, selected: Path(selected),
        launch=launch,
        read_runtime=lambda _project: dict(runtime),
        stop_runtime=lambda project: stops.append(Path(project)),
        resume_runtime=lambda project: resumes.append(Path(project)),
        validate_merge=merge_validator,
        workspace_manager=WorkspaceManager(worktree_root=repo.parent / "worktrees"),
        publish_manager=publish_manager,
        poll_interval=0.05,
        auto_watch=False,
    )


def test_publish_is_explicit_closed_result_action_and_idempotent_by_request(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="worktree", request_id="create-publish")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}

    class Publisher:
        def __init__(self):
            self.calls = []

        def publish(self, prepared, *, branch: str, expected_sha: str):
            self.calls.append((prepared, branch, expected_sha))
            return PublishResult("published", branch, expected_sha)

    publisher = Publisher()
    service = _service(
        tasks,
        repo,
        runtime=runtime,
        launches=[],
        stops=[],
        resumes=[],
        publish_manager=publisher,
    )

    with pytest.raises(ValueError, match="Closed before Publish"):
        service.publish(repo, created["task_id"], request_id="publish-too-early")
    assert publisher.calls == []

    service.start(repo, created["task_id"], request_id="publish-run")
    runtime.update({"running": False, "completed": True})
    closed = service.reconcile(repo, created["task_id"])
    assert closed["status"] == "closed"
    assert closed["run"]["phase"] == "worktree_ready"

    published = service.publish(repo, created["task_id"], request_id="publish-1")
    record = published["run"]["workspace_result"]["publish"]
    assert record["status"] == "published"
    assert record["remote"] == "origin"
    assert record["branch"].startswith("local/task/")
    assert record["sha"] == published["run"]["workspace_result"]["snapshot"]["task_snapshot_sha"]
    assert len(publisher.calls) == 1

    repeated = service.publish(repo, created["task_id"], request_id="publish-1")
    assert repeated["run"]["workspace_result"]["publish"] == record
    assert len(publisher.calls) == 1


def test_invalid_run_request_is_rejected_before_workspace_creation(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main", request_id="create-request-guard")
    runtime = {"running": False, "launching": False, "completed": False, "resumable": False, "actions": {}}
    service = _service(tasks, repo, runtime=runtime, launches=[], stops=[], resumes=[])

    with pytest.raises(ValueError, match="request_id is required"):
        service.start(repo, created["task_id"], request_id="")

    branches = _git(repo, "branch", "--format=%(refname:short)").splitlines()
    assert not [name for name in branches if name.startswith("local/task/")]
    worktree_root = repo.parent / "worktrees"
    assert not worktree_root.exists() or not any(worktree_root.iterdir())


def test_task_list_runs_children_in_order_with_distinct_run_workspaces(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task_list(tasks, repo)
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    launches = []
    service = _service(tasks, repo, runtime=runtime, launches=launches, stops=[], resumes=[])

    first = service.start(repo, created["task_id"], request_id="run-list")
    first_workspace = dict(first["run"]["workspace"])
    assert first["run"]["run_number"] == 1
    assert first["run"]["item_index"] == 0
    assert first["completed_item_count"] == 0
    assert launches[0][1] == "Implement item 1"

    runtime.update({"running": False, "completed": True})
    second = service.reconcile(repo, created["task_id"])
    second_workspace = dict(second["run"]["workspace"])
    assert second["status"] == "ongoing"
    assert second["run"]["run_number"] == 2
    assert second["run"]["item_index"] == 1
    assert second["completed_item_count"] == 1
    assert first_workspace["project_root"] != second_workspace["project_root"]
    assert first_workspace["task_branch"] != second_workspace["task_branch"]
    assert launches[1][1] == "Implement item 2"
    assert len(second["history"]) == 1
    assert second["history"][0]["phase"] == "worktree_ready"

    duplicate_first_request = service.start(
        repo,
        created["task_id"],
        request_id="run-list",
    )
    assert duplicate_first_request["run"]["run_number"] == 2
    assert len(launches) == 2

    closed = service.reconcile(repo, created["task_id"])
    assert closed["status"] == "closed"
    assert closed["completed_item_count"] == 2
    assert closed["run"]["run_number"] == 2
    assert closed["run"]["item_index"] == 1
    assert closed["run"]["phase"] == "worktree_ready"


def test_task_list_restart_between_children_starts_only_next_child(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task_list(tasks, repo)
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    launches = []
    first_service = _service(tasks, repo, runtime=runtime, launches=launches, stops=[], resumes=[])

    first = first_service.start(repo, created["task_id"], request_id="run-list-restart")
    first_workspace = dict(first["run"]["workspace"])
    tasks.transition_run(
        repo,
        created["task_id"],
        1,
        phase="worktree_ready",
        status="ongoing",
        workspace_result={"merge": {"status": "worktree_ready"}},
        completed_item_count=1,
    )

    restarted = _service(tasks, repo, runtime=runtime, launches=launches, stops=[], resumes=[])
    second = restarted.reconcile(repo, created["task_id"])

    assert second["status"] == "ongoing"
    assert second["run"]["run_number"] == 2
    assert second["run"]["item_index"] == 1
    assert second["completed_item_count"] == 1
    assert second["history"][0]["workspace"] == first_workspace
    assert second["run"]["workspace"]["project_root"] != first_workspace["project_root"]
    assert [entry[1] for entry in launches] == [
        "Implement item 1",
        "Implement item 2",
    ]


def test_restart_relaunches_durable_launching_workspace_without_new_identity(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="worktree")
    manager = WorkspaceManager(worktree_root=repo.parent / "worktrees")
    prepared = manager.prepare(
        repo,
        task_id=created["task_id"],
        run_number=1,
        requested_mode="worktree",
        execution_settings={
            "auto_workspace_policy": "busy-worktree",
            "allow_concurrent_main_tasks": False,
        },
        main_running=False,
    )
    tasks.begin_run(
        repo,
        created["task_id"],
        request_id="durable-before-launch",
        workspace=prepared.as_dict(),
    )
    runtime = {
        "running": False,
        "launching": False,
        "completed": False,
        "resumable": False,
        "stale": False,
        "has_state": False,
        "actions": {},
    }
    launches = []
    restarted = _service(tasks, repo, runtime=runtime, launches=launches, stops=[], resumes=[])

    running = restarted.reconcile(repo, created["task_id"])

    assert running["status"] == "ongoing"
    assert running["run"]["phase"] == "running"
    assert running["run"]["run_number"] == 1
    assert running["run"]["workspace"] == prepared.as_dict()
    assert len(launches) == 1
    assert launches[0][0] == prepared.project_root
    assert launches[0][1] == "Implement one"


def test_quick_goal_create_and_run_is_idempotent(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, w: {"exists": Path(w).name == "workflow.yaml"})
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    launches = []
    service = _service(tasks, repo, runtime=runtime, launches=launches, stops=[], resumes=[])

    first = service.start_goal(
        repo,
        "Implement the quick goal",
        request_id="goal-command-1",
        project_id="project-fixture",
    )
    duplicate = service.start_goal(
        repo,
        "Implement the quick goal",
        request_id="goal-command-1",
        project_id="project-fixture",
    )

    assert first["goal_run_started"] is True
    assert first["status"] == "ongoing"
    assert first["run"]["phase"] == "running"
    assert first["run"]["workspace"]["requested_mode"] == "auto"
    assert first["items"][0]["prompt"] == "Implement the quick goal"
    assert first["items"][0]["workflow"] == str(repo / "workflow.yaml")
    assert duplicate["task_id"] == first["task_id"]
    assert duplicate["run_count"] == 1
    assert len(tasks.list(repo)["tasks"]) == 1
    assert len(launches) == 1


def test_quick_goal_defaults_to_ralphy_and_fails_closed_for_invalid_inputs(tmp_path: Path):
    repo = _repo(tmp_path)
    accepted = []

    def requirements(_project: Path, workflow: str):
        accepted.append(workflow)
        return {
            "exists": workflow == "ralphy_ai_validate.yaml",
            "requires_python_validator": workflow == "validator.workflow.yaml",
        }

    tasks = TaskService(workflow_requirements=requirements)
    service = TaskRunService(
        tasks,
        execution_settings=lambda: {
            "auto_workspace_policy": "busy-worktree",
            "merge_failure_limit": 3,
            "allow_concurrent_main_tasks": False,
        },
        preferences=lambda _project: {"agent": "qwen", "model": "", "mode": "auto", "workflow": ""},
        backend_default=lambda _project: "qwen",
        resolve_workflow=lambda _project, selected: Path(selected),
        launch=lambda *_args, **_kwargs: None,
        read_runtime=lambda _project: {"running": True, "launching": False, "completed": False, "actions": {}},
        stop_runtime=lambda _project: None,
        resume_runtime=lambda _project: None,
        workspace_manager=WorkspaceManager(worktree_root=repo.parent / "worktrees"),
        auto_watch=False,
    )

    with pytest.raises(ValueError, match="@goal spec is required"):
        service.start_goal(repo, "   ", request_id="empty-goal")
    assert tasks.list(repo)["tasks"] == []

    started = service.start_goal(repo, "Fallback workflow", request_id="goal-fallback")
    assert started["items"][0]["workflow"] == "ralphy_ai_validate.yaml"
    assert "ralphy_ai_validate.yaml" in accepted

    missing_tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": False})
    before_missing = missing_tasks.list(repo)["tasks"]
    missing = TaskRunService(
        missing_tasks,
        execution_settings=lambda: {"auto_workspace_policy": "busy-worktree", "merge_failure_limit": 3, "allow_concurrent_main_tasks": False},
        preferences=lambda _project: {"agent": "qwen", "model": "", "mode": "auto", "workflow": "missing.workflow.yaml"},
        backend_default=lambda _project: "qwen",
        resolve_workflow=lambda _project, selected: Path(selected),
        launch=lambda *_args, **_kwargs: None,
        read_runtime=lambda _project: {},
        stop_runtime=lambda _project: None,
        resume_runtime=lambda _project: None,
        workspace_manager=WorkspaceManager(worktree_root=repo.parent / "missing-worktrees"),
        auto_watch=False,
    )
    with pytest.raises(ValueError, match="Workflow does not exist"):
        missing.start_goal(repo, "Missing workflow", request_id="goal-missing")
    assert missing_tasks.list(repo)["tasks"] == before_missing

    validator_tasks = TaskService(
        workflow_requirements=lambda _p, _w: {"exists": True, "requires_python_validator": True}
    )
    before_validator = validator_tasks.list(repo)["tasks"]
    validator = TaskRunService(
        validator_tasks,
        execution_settings=lambda: {"auto_workspace_policy": "busy-worktree", "merge_failure_limit": 3, "allow_concurrent_main_tasks": False},
        preferences=lambda _project: {"agent": "qwen", "model": "", "mode": "auto", "workflow": "validator.workflow.yaml"},
        backend_default=lambda _project: "qwen",
        resolve_workflow=lambda _project, selected: Path(selected),
        launch=lambda *_args, **_kwargs: None,
        read_runtime=lambda _project: {},
        stop_runtime=lambda _project: None,
        resume_runtime=lambda _project: None,
        workspace_manager=WorkspaceManager(worktree_root=repo.parent / "validator-worktrees"),
        auto_watch=False,
    )
    with pytest.raises(ValueError, match="File Validator is required"):
        validator.start_goal(repo, "Needs validator", request_id="goal-validator")
    assert validator_tasks.list(repo)["tasks"] == before_validator


@pytest.mark.parametrize(
    ("policy", "expected_mode", "expected_started"),
    [
        ("busy-worktree", "worktree", True),
        ("always-worktree", "worktree", True),
        ("always-main", None, False),
    ],
)
def test_quick_goal_main_busy_uses_global_auto_policy(
    tmp_path: Path, policy: str, expected_mode: str | None, expected_started: bool
):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    existing = _task(tasks, repo, workspace="main", request_id=f"existing-{policy}")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    launches = []
    service = _service(
        tasks,
        repo,
        runtime=runtime,
        launches=launches,
        stops=[],
        resumes=[],
        settings={
            "auto_workspace_policy": policy,
            "merge_failure_limit": 3,
            "allow_concurrent_main_tasks": False,
        },
    )
    service.start(repo, existing["task_id"], request_id=f"existing-run-{policy}")

    goal = service.start_goal(repo, "Busy quick goal", request_id=f"goal-busy-{policy}")

    assert goal["goal_run_started"] is expected_started
    if expected_started:
        assert goal["status"] == "ongoing"
        assert goal["run"]["workspace"]["effective_mode"] == expected_mode
        assert len(launches) == 2
    else:
        assert goal["status"] == "new"
        assert "run" not in goal
        assert "busy" in goal["goal_run_error"].lower()
        assert len(launches) == 1
        tasks.transition_run(
            repo, existing["task_id"], 1, phase="stopped", status="paused"
        )
        retried = service.start_goal(repo, "Busy quick goal", request_id=f"goal-busy-{policy}")
        assert retried["task_id"] == goal["task_id"]
        assert retried["goal_run_started"] is True
        assert retried["run"]["workspace"]["effective_mode"] == "main"
        assert len(tasks.list(repo)["tasks"]) == 2


def test_quick_goal_launch_failure_is_durable_paused_and_not_relaunched(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    calls = []

    def fail_launch(project: Path, _goal: str | None, **_kwargs):
        calls.append(Path(project))
        raise RuntimeError("quick goal launch failed")

    service = TaskRunService(
        tasks,
        execution_settings=lambda: {"auto_workspace_policy": "busy-worktree", "merge_failure_limit": 3, "allow_concurrent_main_tasks": False},
        preferences=lambda _project: {"agent": "qwen", "model": "", "mode": "auto", "workflow": str(repo / "workflow.yaml")},
        backend_default=lambda _project: "qwen",
        resolve_workflow=lambda _project, selected: Path(selected),
        launch=fail_launch,
        read_runtime=lambda _project: {"running": False, "launching": False, "completed": False, "actions": {}},
        stop_runtime=lambda _project: None,
        resume_runtime=lambda _project: None,
        workspace_manager=WorkspaceManager(worktree_root=repo.parent / "worktrees"),
        auto_watch=False,
    )

    failed = service.start_goal(repo, "Launch failure", request_id="goal-launch-fail")
    duplicate = service.start_goal(repo, "Launch failure", request_id="goal-launch-fail")

    assert failed["goal_run_started"] is False
    assert failed["status"] == "paused"
    assert failed["run"]["phase"] == "launch_failed"
    assert "quick goal launch failed" in failed["goal_run_error"]
    assert duplicate["task_id"] == failed["task_id"]
    assert duplicate["run"]["workspace"] == failed["run"]["workspace"]
    assert duplicate["goal_run_started"] is False
    assert len(calls) == 1


def test_concurrent_main_tasks_run_in_distinct_isolated_worktrees(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    first = _task(
        tasks,
        repo,
        workspace="main",
        request_id="create-main-a",
        title="Main A",
    )
    second = _task(
        tasks,
        repo,
        workspace="main",
        request_id="create-main-b",
        title="Main B",
    )
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    launches = []
    service = _service(
        tasks,
        repo,
        runtime=runtime,
        launches=launches,
        stops=[],
        resumes=[],
        settings={
            "auto_workspace_policy": "always-main",
            "merge_failure_limit": 3,
            "allow_concurrent_main_tasks": True,
        },
    )

    running_a = service.start(repo, first["task_id"], request_id="run-main-a")
    running_b = service.start(repo, second["task_id"], request_id="run-main-b")

    workspace_a = running_a["run"]["workspace"]
    workspace_b = running_b["run"]["workspace"]
    assert running_a["status"] == running_b["status"] == "ongoing"
    assert workspace_a["effective_mode"] == workspace_b["effective_mode"] == "main"
    assert workspace_a["target_branch"] == workspace_b["target_branch"] == "main"
    assert workspace_a["task_branch"] != workspace_b["task_branch"]
    assert workspace_a["project_root"] != workspace_b["project_root"]
    assert launches[0][0] == Path(workspace_a["project_root"])
    assert launches[1][0] == Path(workspace_b["project_root"])
    assert not (repo / "result.txt").exists()


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


def test_rerun_request_recovers_when_lifecycle_reset_was_durable_before_start(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="worktree", request_id="create-rerun-gap")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    launches = []
    service = _service(tasks, repo, runtime=runtime, launches=launches, stops=[], resumes=[])

    service.start(repo, created["task_id"], request_id="rerun-gap-first")
    runtime.update({"running": False, "completed": True})
    assert service.reconcile(repo, created["task_id"])["status"] == "closed"

    tasks.reset_to_new(
        repo,
        created["task_id"],
        request_id="rerun-gap-lifecycle",
        action="rerun",
    )
    assert tasks.get(repo, created["task_id"])["status"] == "new"
    assert tasks.run_request(
        repo,
        "task-rerun-" + hashlib.sha256(b"rerun-gap-lifecycle").hexdigest(),
    ) is None

    runtime.update({"running": True, "completed": False})
    resumed = service.rerun(
        repo,
        created["task_id"],
        request_id="rerun-gap-lifecycle",
    )
    assert resumed["status"] == "ongoing"
    assert resumed["run_count"] == 2
    assert len(launches) == 2


def test_task_lifecycle_guards_reject_invalid_status_before_git_side_effects(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="worktree", request_id="create-lifecycle-guard")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    service = _service(tasks, repo, runtime=runtime, launches=[], stops=[], resumes=[])

    with pytest.raises(ValueError, match="Paused before Reset"):
        service.reset(repo, created["task_id"], request_id="invalid-reset-new")
    with pytest.raises(ValueError, match="Paused or Closed before Rerun"):
        service.rerun(repo, created["task_id"], request_id="invalid-rerun-new")

    started = service.start(repo, created["task_id"], request_id="guard-run")
    runtime.update({"running": False, "completed": True})
    closed = service.reconcile(repo, created["task_id"])
    assert closed["status"] == "closed"
    retained = Path(started["run"]["workspace"]["worktree_path"])

    with pytest.raises(ValueError, match="Paused before Reset"):
        service.reset(repo, created["task_id"], request_id="invalid-reset-closed")
    unchanged = tasks.get(repo, created["task_id"])
    assert unchanged["status"] == "closed"
    assert unchanged["run"]["run_number"] == 1
    assert retained.is_dir()


def test_paused_reset_returns_task_to_new_and_retains_archived_workspace(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="worktree", request_id="create-reset")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {"stop": True}}
    launches, stops, resumes = [], [], []
    service = _service(tasks, repo, runtime=runtime, launches=launches, stops=stops, resumes=resumes)

    started = service.start(repo, created["task_id"], request_id="reset-run")
    retained = Path(started["run"]["workspace"]["worktree_path"])
    service.stop(repo, created["task_id"])
    tasks.transition_run(
        repo,
        created["task_id"],
        1,
        phase="stopped",
        status="paused",
    )

    reset = service.reset(repo, created["task_id"], request_id="reset-lifecycle-1")
    assert reset["status"] == "new"
    assert reset["completed_item_count"] == 0
    assert "run" not in reset
    assert reset["history"][-1]["phase"] == "stopped"
    assert reset["history"][-1]["lifecycle_end"] == "reset"
    assert reset["edit_policy"]["can_delete"] is False
    assert retained.is_dir()

    duplicate = service.reset(repo, created["task_id"], request_id="reset-lifecycle-1")
    assert duplicate["status"] == "new"
    assert len(duplicate["history"]) == 1
    with pytest.raises(ValueError, match="Only New Tasks"):
        tasks.delete(repo, created["task_id"], request_id="delete-retained-reset")


def test_rerun_closed_task_uses_fresh_run_workspace_and_is_idempotent(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="worktree", request_id="create-rerun")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    launches = []
    service = _service(tasks, repo, runtime=runtime, launches=launches, stops=[], resumes=[])

    first = service.start(repo, created["task_id"], request_id="first-rerun-source")
    original_workspace = Path(first["run"]["workspace"]["worktree_path"])
    runtime.update({"running": False, "completed": True})
    closed = service.reconcile(repo, created["task_id"])
    assert closed["status"] == "closed"

    runtime.update({"running": True, "completed": False})
    rerun = service.rerun(repo, created["task_id"], request_id="rerun-lifecycle-1")
    fresh_workspace = Path(rerun["run"]["workspace"]["worktree_path"])
    assert rerun["status"] == "ongoing"
    assert rerun["run_count"] == 2
    assert rerun["run"]["run_number"] == 2
    assert fresh_workspace != original_workspace
    assert original_workspace.is_dir()
    assert fresh_workspace.is_dir()
    assert rerun["history"][-1]["lifecycle_end"] == "rerun"
    assert rerun["history"][-1]["phase"] == "worktree_ready"
    assert len(launches) == 2

    duplicate = service.rerun(repo, created["task_id"], request_id="rerun-lifecycle-1")
    assert duplicate["run_count"] == 2
    assert duplicate["run"]["workspace"]["worktree_path"] == str(fresh_workspace)
    assert len(launches) == 2


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


def test_main_target_advance_runs_validation_only_callback_before_commit(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main", request_id="create-validated-main")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    validations = []

    def validate(project: Path, goal: str, **kwargs):
        validations.append((Path(project), goal, dict(kwargs)))
        assert (Path(project) / "result.txt").read_text(encoding="utf-8") == "done\n"
        assert (Path(project) / "target.txt").read_text(encoding="utf-8") == "target advanced\n"
        return "PASS"

    service = _service(
        tasks,
        repo,
        runtime=runtime,
        launches=[],
        stops=[],
        resumes=[],
        merge_validator=validate,
    )
    service.start(repo, created["task_id"], request_id="validated-main")
    (repo / "target.txt").write_text("target advanced\n", encoding="utf-8")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "advance target")
    runtime.update({"running": False, "completed": True})

    closed = service.reconcile(repo, created["task_id"])

    assert closed["status"] == "closed"
    assert closed["run"]["phase"] == "merged"
    assert closed["run"]["workspace_result"]["merge"]["verdict"] == "PASS"
    assert len(validations) == 1
    assert validations[0][1] == "Implement one"
    assert validations[0][2]["workflow"] == str(repo / "workflow.yaml")


def test_merge_validation_source_fail_counts_once_and_starts_recovery(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main", request_id="create-source-fail")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    launches = []
    service = _service(
        tasks,
        repo,
        runtime=runtime,
        launches=launches,
        stops=[],
        resumes=[],
        merge_validator=lambda _project, _goal, **_kwargs: "SOURCE_FAIL",
    )

    service.start(repo, created["task_id"], request_id="source-fail-run")
    (repo / "target.txt").write_text("target advanced\n", encoding="utf-8")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "advance target")
    runtime.update({"running": False, "completed": True})

    recovering = service.reconcile(repo, created["task_id"])

    assert recovering["status"] == "ongoing"
    assert recovering["run"]["phase"] == "conflict_recovery"
    assert recovering["merge_failure_count"] == 1
    failure = recovering["run"]["workspace_result"]["last_merge_failure"]
    assert failure["status"] == "source_fail"
    assert failure["verdict"] == "SOURCE_FAIL"
    assert recovering["run"]["workspace_result"]["recovery"]["status"] == "running"
    assert "Merge-repair task only" in launches[-1][1]


def test_merge_validation_technical_error_does_not_count_or_create_recovery(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    created = _task(tasks, repo, workspace="main", request_id="create-technical-validation")
    runtime = {"running": True, "launching": False, "completed": False, "resumable": False, "actions": {}}
    service = _service(
        tasks,
        repo,
        runtime=runtime,
        launches=[],
        stops=[],
        resumes=[],
        merge_validator=lambda _project, _goal, **_kwargs: "TECHNICAL_ERROR",
    )

    service.start(repo, created["task_id"], request_id="technical-validation-run")
    (repo / "target.txt").write_text("target advanced\n", encoding="utf-8")
    _git(repo, "add", "target.txt")
    _git(repo, "commit", "-m", "advance target")
    runtime.update({"running": False, "completed": True})

    blocked = service.reconcile(repo, created["task_id"])

    assert blocked["status"] == "ongoing"
    assert blocked["run"]["phase"] == "technical_error"
    assert blocked["merge_failure_count"] == 0
    assert "recovery" not in blocked["run"]["workspace_result"]


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


def test_reset_abandons_conflict_recovery_and_releases_main_merge_queue(tmp_path: Path):
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    first = _task(
        tasks,
        repo,
        workspace="main",
        request_id="create-reset-conflict",
        title="Conflict head",
    )
    runtime = {
        "running": True,
        "launching": False,
        "completed": False,
        "resumable": False,
        "actions": {},
    }
    launches = []
    service = _service(tasks, repo, runtime=runtime, launches=launches, stops=[], resumes=[])

    started = service.start(repo, first["task_id"], request_id="reset-conflict-run")
    original_root = Path(started["run"]["workspace"]["project_root"])
    (original_root / "app.txt").write_text("task side\n", encoding="utf-8")
    (repo / "app.txt").write_text("target side\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "target side")

    runtime.update({"running": False, "completed": True})
    recovering = service.reconcile(repo, first["task_id"])
    assert recovering["run"]["phase"] == "conflict_recovery"
    recovery_root = Path(
        recovering["run"]["workspace_result"]["recovery"]["workspace"]["project_root"]
    )
    assert recovery_root.is_dir()

    runtime.update({
        "running": False,
        "completed": False,
        "resumable": True,
        "actions": {"resume": True},
    })
    paused = service.reconcile(repo, first["task_id"])
    assert paused["status"] == "paused"
    assert paused["run"]["phase"] == "recovery_stopped"

    reset = service.reset(
        repo,
        first["task_id"],
        request_id="reset-conflict-lifecycle",
    )
    assert reset["status"] == "new"
    assert original_root.is_dir()
    assert recovery_root.is_dir()

    second = _task(
        tasks,
        repo,
        workspace="main",
        request_id="create-after-reset",
        title="Next Main",
    )
    runtime.update({
        "running": True,
        "completed": False,
        "resumable": False,
        "actions": {},
    })
    service.start(repo, second["task_id"], request_id="after-reset-run")
    runtime.update({"running": False, "completed": True})
    delivered = service.reconcile(repo, second["task_id"])
    assert delivered["status"] == "closed"
    assert delivered["run"]["phase"] == "merged"
    assert delivered["run"]["workspace_result"]["merge"]["status"] == "merged"


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
