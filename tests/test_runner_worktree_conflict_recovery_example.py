from __future__ import annotations

import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ui.task_run_service import TaskRunService
from ui.task_service import TaskService
from workspace import WorkspaceManager

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "ai_task_runner.py"
AGENT = ROOT / "tests" / "conflict_recovery_agent.py"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Concurrent Runner Test")
    _git(repo, "config", "user.email", "runner-conflict@example.invalid")
    (repo / "app.txt").write_text("base\n", encoding="utf-8")
    (repo / "workflow.yaml").write_text("stages: {}\nflow: []\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    return repo


def _task(tasks: TaskService, repo: Path, marker: str) -> dict:
    return tasks.create(
        repo,
        {
            "title": marker,
            "items": [{
                "title": marker,
                "prompt": f"{marker}: update app.txt",
                "workflow": str(repo / "workflow.yaml"),
                "project": str(repo),
                # Main delivery still executes inside an isolated Task worktree.
                # This is the production path that automatically merges back.
                "workspace": "main",
            }],
        },
        request_id=f"create-{marker.lower()}",
    )


def test_two_concurrent_runner_worktrees_auto_recover_conflict_and_merge(
    tmp_path: Path,
) -> None:
    """End-to-end example: two Runners -> two worktrees -> conflict -> recovery -> merge.

    The real Runner supervisor/worker subprocesses, WorkspaceManager, snapshots,
    MergeManager and TaskRunService are used. Only the model is deterministic so
    this remains an offline CI test.
    """
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    task_a = _task(tasks, repo, "TASK_A")
    task_b = _task(tasks, repo, "TASK_B")

    runtime: dict[Path, dict] = {}
    runtime_lock = threading.Lock()
    initial_launch_barrier = threading.Barrier(2)
    launches: list[tuple[Path, str]] = []
    agent_command = subprocess.list2cmdline([sys.executable, str(AGENT)])

    def launch(project: Path, goal: str | None, **_kwargs) -> None:
        project = Path(project).resolve()
        goal_text = str(goal or "")
        is_recovery = goal_text.startswith("Merge-repair task only.")

        with runtime_lock:
            launches.append((project, goal_text))
            runtime[project] = {
                "running": True,
                "launching": False,
                "completed": False,
                "resumable": False,
                "stale": False,
                "has_state": True,
                "actions": {},
            }

        # Force both initial Task Runners to overlap after their worktrees have
        # been prepared. Recovery is intentionally not part of this barrier.
        if not is_recovery:
            initial_launch_barrier.wait(timeout=30)

        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--goal",
                goal_text,
                "--project-root",
                str(project),
                "--validator",
                "ai",
                "--backend",
                "qwen",
                "--command",
                agent_command,
                "--stage-retries",
                "1",
                "--retry-delay",
                "0",
                "--retry-max-delay",
                "0",
                "--agent-timeout",
                "30",
                "--planning-timeout",
                "30",
                "--validator-timeout",
                "30",
                "--agent-idle-after-change-timeout",
                "0",
                "--final-ai-validations",
                "1",
                "--final-ai-required-passes",
                "1",
                "--no-ui-project-register",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=90,
        )
        assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr

        with runtime_lock:
            runtime[project] = {
                "running": False,
                "launching": False,
                "completed": True,
                "resumable": False,
                "stale": False,
                "has_state": True,
                "actions": {},
            }

    def read_runtime(project: Path) -> dict:
        with runtime_lock:
            return dict(runtime.get(Path(project).resolve(), {
                "running": False,
                "launching": False,
                "completed": False,
                "resumable": False,
                "stale": False,
                "has_state": False,
                "actions": {},
            }))

    service = TaskRunService(
        tasks,
        execution_settings=lambda: {
            "auto_workspace_policy": "always-main",
            "merge_failure_limit": 3,
            "allow_concurrent_main_tasks": True,
        },
        preferences=lambda _project: {
            "agent": "qwen",
            "model": "",
            "mode": "auto",
            "workflow": str(repo / "workflow.yaml"),
        },
        backend_default=lambda _project: "qwen",
        resolve_workflow=lambda _project, selected: Path(selected),
        launch=launch,
        read_runtime=read_runtime,
        stop_runtime=lambda _project: None,
        resume_runtime=lambda _project: None,
        workspace_manager=WorkspaceManager(worktree_root=tmp_path / "worktrees"),
        poll_interval=0.05,
        auto_watch=False,
    )

    # Start both Tasks concurrently. Each Task really runs the Runner in its own
    # isolated worktree, while both capture the same initial target HEAD.
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(
            service.start,
            repo,
            task_a["task_id"],
            request_id="run-task-a",
        )
        future_b = pool.submit(
            service.start,
            repo,
            task_b["task_id"],
            request_id="run-task-b",
        )
        started_a = future_a.result(timeout=60)
        started_b = future_b.result(timeout=60)

    workspace_a = started_a["run"]["workspace"]
    workspace_b = started_b["run"]["workspace"]
    root_a = Path(workspace_a["project_root"])
    root_b = Path(workspace_b["project_root"])

    assert workspace_a["effective_mode"] == "main"
    assert workspace_b["effective_mode"] == "main"
    assert workspace_a["task_base_sha"] == workspace_b["task_base_sha"]
    assert workspace_a["task_branch"] != workspace_b["task_branch"]
    assert root_a != root_b
    assert root_a != repo.resolve()
    assert root_b != repo.resolve()
    assert root_a.joinpath("app.txt").read_text(encoding="utf-8") == "task-a\n"
    assert root_b.joinpath("app.txt").read_text(encoding="utf-8") == "task-b\n"
    # Neither Runner may mutate the target Project before delivery.
    assert (repo / "app.txt").read_text(encoding="utf-8") == "base\n"

    # Task A wins the FIFO delivery race and merges first.
    closed_a = service.reconcile(repo, task_a["task_id"])
    assert closed_a["status"] == "closed"
    assert closed_a["run"]["phase"] == "merged"
    assert (repo / "app.txt").read_text(encoding="utf-8") == "task-a\n"
    task_a_target_head = _git(repo, "rev-parse", "HEAD")

    # Task B was produced from the same base and edits the same line. Its direct
    # merge must conflict. Production orchestration automatically prepares a
    # latest-target recovery worktree and launches Runner with a merge-repair prompt.
    recovering_b = service.reconcile(repo, task_b["task_id"])
    assert recovering_b["status"] == "ongoing"
    assert recovering_b["run"]["phase"] == "conflict_recovery"
    assert recovering_b["merge_failure_count"] == 1

    workspace_result = recovering_b["run"]["workspace_result"]
    failure = workspace_result["last_merge_failure"]
    recovery = workspace_result["recovery"]
    recovery_root = Path(recovery["workspace"]["project_root"])

    assert failure["status"] == "conflict"
    assert failure["conflict_files"] == ["app.txt"]
    assert recovery["status"] == "running"
    assert recovery["workspace"]["task_base_sha"] == task_a_target_head
    assert recovery_root != root_b
    assert recovery_root.joinpath("app.txt").read_text(encoding="utf-8") == "task-a + task-b\n"
    assert "Merge-repair task only" in recovery["prompt"]
    assert "TASK_B" in recovery["prompt"]
    assert "app.txt" in recovery["prompt"]
    assert Path(recovery["patch_path"]).is_file()
    assert "task-b" in Path(recovery["patch_path"]).read_text(encoding="utf-8")

    # The recovery Runner already completed synchronously. Reconcile snapshots
    # that recovery worktree and merges it into the latest target automatically.
    closed_b = service.reconcile(repo, task_b["task_id"])
    assert closed_b["status"] == "closed"
    assert closed_b["run"]["phase"] == "merged"
    assert closed_b["merge_failure_count"] == 1
    assert (repo / "app.txt").read_text(encoding="utf-8") == "task-a + task-b\n"

    final_result = closed_b["run"]["workspace_result"]
    assert final_result["merge"]["status"] == "merged"
    assert final_result["recovery"]["status"] == "completed"
    assert final_result["merge_source"]["workspace"]["task_branch"].startswith(
        f"local/recovery/{task_b['task_id']}-r1-f1"
    )

    # Original Task B output is immutable evidence; recovery is incremental and
    # does not rewrite the first Task worktree or the original Task B worktree.
    assert root_a.joinpath("app.txt").read_text(encoding="utf-8") == "task-a\n"
    assert root_b.joinpath("app.txt").read_text(encoding="utf-8") == "task-b\n"

    # Two initial Runner launches + one automatic recovery Runner launch.
    assert len(launches) == 3
    assert sum(goal.startswith("Merge-repair task only.") for _root, goal in launches) == 1

    # Both deliveries are explicit --no-ff merge boundaries in Project history.
    merge_count = int(_git(repo, "rev-list", "--merges", "--count", "HEAD"))
    assert merge_count == 2

def test_three_concurrent_runner_worktrees_recover_in_fifo_against_latest_main(
    tmp_path: Path,
) -> None:
    """Production-path E2E for three concurrent Tasks and chained conflict recovery.

    This proves that a later recovery is created from the latest merged target,
    not from the original Task base, while a third Task remains pending behind
    the recovery queue head.
    """
    repo = _repo(tmp_path)
    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    task_a = _task(tasks, repo, "TASK_A")
    task_b = _task(tasks, repo, "TASK_B")
    task_c = _task(tasks, repo, "TASK_C")

    runtime: dict[Path, dict] = {}
    runtime_lock = threading.Lock()
    initial_launch_barrier = threading.Barrier(3)
    launches: list[tuple[Path, str]] = []
    agent_command = subprocess.list2cmdline([sys.executable, str(AGENT)])

    def launch(project: Path, goal: str | None, **_kwargs) -> None:
        project = Path(project).resolve()
        goal_text = str(goal or "")
        is_recovery = goal_text.startswith("Merge-repair task only.")

        with runtime_lock:
            launches.append((project, goal_text))
            runtime[project] = {
                "running": True,
                "launching": False,
                "completed": False,
                "resumable": False,
                "stale": False,
                "has_state": True,
                "actions": {},
            }

        if not is_recovery:
            initial_launch_barrier.wait(timeout=30)

        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--goal",
                goal_text,
                "--project-root",
                str(project),
                "--validator",
                "ai",
                "--backend",
                "qwen",
                "--command",
                agent_command,
                "--stage-retries",
                "1",
                "--retry-delay",
                "0",
                "--retry-max-delay",
                "0",
                "--agent-timeout",
                "30",
                "--planning-timeout",
                "30",
                "--validator-timeout",
                "30",
                "--agent-idle-after-change-timeout",
                "0",
                "--final-ai-validations",
                "1",
                "--final-ai-required-passes",
                "1",
                "--no-ui-project-register",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=90,
        )
        assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr

        with runtime_lock:
            runtime[project] = {
                "running": False,
                "launching": False,
                "completed": True,
                "resumable": False,
                "stale": False,
                "has_state": True,
                "actions": {},
            }

    def read_runtime(project: Path) -> dict:
        with runtime_lock:
            return dict(runtime.get(Path(project).resolve(), {
                "running": False,
                "launching": False,
                "completed": False,
                "resumable": False,
                "stale": False,
                "has_state": False,
                "actions": {},
            }))

    service = TaskRunService(
        tasks,
        execution_settings=lambda: {
            "auto_workspace_policy": "always-main",
            "merge_failure_limit": 3,
            "allow_concurrent_main_tasks": True,
        },
        preferences=lambda _project: {
            "agent": "qwen",
            "model": "",
            "mode": "auto",
            "workflow": str(repo / "workflow.yaml"),
        },
        backend_default=lambda _project: "qwen",
        resolve_workflow=lambda _project, selected: Path(selected),
        launch=launch,
        read_runtime=read_runtime,
        stop_runtime=lambda _project: None,
        resume_runtime=lambda _project: None,
        workspace_manager=WorkspaceManager(worktree_root=tmp_path / "worktrees"),
        poll_interval=0.05,
        auto_watch=False,
    )

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(service.start, repo, task["task_id"], request_id=f"run-{label}")
            for task, label in (
                (task_a, "task-a"),
                (task_b, "task-b"),
                (task_c, "task-c"),
            )
        ]
        started_a, started_b, started_c = [
            future.result(timeout=60) for future in futures
        ]

    workspaces = [
        started_a["run"]["workspace"],
        started_b["run"]["workspace"],
        started_c["run"]["workspace"],
    ]
    roots = [Path(workspace["project_root"]) for workspace in workspaces]
    assert len({workspace["task_base_sha"] for workspace in workspaces}) == 1
    assert len({workspace["task_branch"] for workspace in workspaces}) == 3
    assert len({root.resolve() for root in roots}) == 3
    assert [root.joinpath("app.txt").read_text(encoding="utf-8") for root in roots] == [
        "task-a\n",
        "task-b\n",
        "task-c\n",
    ]
    assert (repo / "app.txt").read_text(encoding="utf-8") == "base\n"

    closed_a = service.reconcile(repo, task_a["task_id"])
    assert closed_a["status"] == "closed"
    assert closed_a["run"]["phase"] == "merged"
    assert (repo / "app.txt").read_text(encoding="utf-8") == "task-a\n"
    head_after_a = _git(repo, "rev-parse", "HEAD")

    recovering_b = service.reconcile(repo, task_b["task_id"])
    assert recovering_b["status"] == "ongoing"
    assert recovering_b["run"]["phase"] == "conflict_recovery"
    recovery_b = recovering_b["run"]["workspace_result"]["recovery"]
    recovery_b_root = Path(recovery_b["workspace"]["project_root"])
    assert recovery_b["workspace"]["task_base_sha"] == head_after_a
    assert recovery_b_root.joinpath("app.txt").read_text(encoding="utf-8") == (
        "task-a + task-b\n"
    )
    assert "TASK_B" in recovery_b["prompt"]
    assert "task-b" in Path(recovery_b["patch_path"]).read_text(encoding="utf-8")

    # C reaches delivery while B still owns the FIFO head. It must not overtake
    # B or mutate Main before B's recovery snapshot is merged.
    waiting_c = service.reconcile(repo, task_c["task_id"])
    assert waiting_c["status"] == "ongoing"
    assert waiting_c["run"]["phase"] == "pending_merge"
    assert waiting_c["run"]["workspace_result"]["merge"]["status"] == "pending_merge"
    assert (repo / "app.txt").read_text(encoding="utf-8") == "task-a\n"

    closed_b = service.reconcile(repo, task_b["task_id"])
    assert closed_b["status"] == "closed"
    assert closed_b["run"]["phase"] == "merged"
    assert (repo / "app.txt").read_text(encoding="utf-8") == "task-a + task-b\n"
    head_after_b = _git(repo, "rev-parse", "HEAD")
    assert head_after_b != head_after_a

    # C now becomes queue head. Its original snapshot conflicts, so recovery C
    # must be based on the target that already contains both A and recovered B.
    recovering_c = service.reconcile(repo, task_c["task_id"])
    assert recovering_c["status"] == "ongoing"
    assert recovering_c["run"]["phase"] == "conflict_recovery"
    assert recovering_c["merge_failure_count"] == 1
    result_c = recovering_c["run"]["workspace_result"]
    assert result_c["last_merge_failure"]["status"] == "conflict"
    assert result_c["last_merge_failure"]["conflict_files"] == ["app.txt"]

    recovery_c = result_c["recovery"]
    recovery_c_root = Path(recovery_c["workspace"]["project_root"])
    assert recovery_c["workspace"]["task_base_sha"] == head_after_b
    assert recovery_c_root.joinpath("app.txt").read_text(encoding="utf-8") == (
        "task-a + task-b + task-c\n"
    )
    assert "TASK_C" in recovery_c["prompt"]
    assert "task-c" in Path(recovery_c["patch_path"]).read_text(encoding="utf-8")

    closed_c = service.reconcile(repo, task_c["task_id"])
    assert closed_c["status"] == "closed"
    assert closed_c["run"]["phase"] == "merged"
    assert closed_c["merge_failure_count"] == 1
    assert (repo / "app.txt").read_text(encoding="utf-8") == (
        "task-a + task-b + task-c\n"
    )
    source_status = _git(
        repo,
        "status",
        "--porcelain",
        "--",
        ".",
        ":(exclude).ai-task-runner",
        ":(exclude).ai-task-runner/**",
    )
    assert source_status == ""

    # Original outputs remain immutable evidence and are never rewritten by
    # conflict recovery.
    assert roots[0].joinpath("app.txt").read_text(encoding="utf-8") == "task-a\n"
    assert roots[1].joinpath("app.txt").read_text(encoding="utf-8") == "task-b\n"
    assert roots[2].joinpath("app.txt").read_text(encoding="utf-8") == "task-c\n"

    assert len(launches) == 5
    recovery_goals = [
        goal for _root, goal in launches if goal.startswith("Merge-repair task only.")
    ]
    assert len(recovery_goals) == 2
    assert any("TASK_B" in goal for goal in recovery_goals)
    assert any("TASK_C" in goal for goal in recovery_goals)
    assert int(_git(repo, "rev-list", "--merges", "--count", "HEAD")) == 3

