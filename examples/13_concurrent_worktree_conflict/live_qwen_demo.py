#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = Path(__file__).resolve().parent
RUNNER = ROOT / "ai_task_runner.py"
RALPHY_WORKFLOW = ROOT / "runner" / "assets" / "workflows" / "ralphy_ai_validate.yaml"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.task_run_service import TaskRunService  # noqa: E402
from ui.task_service import TaskService  # noqa: E402
from workspace import WorkspaceManager  # noqa: E402


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout.strip()


def _source_status_ignoring_runner_runtime(project: Path) -> str:
    """Match production MergeManager target-clean semantics.

    TaskService intentionally persists lifecycle state under .ai-task-runner.
    That runner-owned metadata must not make the source Project appear dirty,
    while every other uncommitted Project change remains a hard failure.
    """
    return _git(
        project,
        "status",
        "--porcelain=v1",
        "--",
        ".",
        ":(exclude).ai-task-runner",
        ":(exclude).ai-task-runner/**",
    )


def _init_project(base: Path) -> Path:
    project = base / "project"
    project.mkdir(parents=True)
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "AI Task Runner Live Qwen Demo")
    _git(project, "config", "user.email", "live-qwen-demo@example.invalid")
    (project / "shared.txt").write_text("enabled_tasks=BASE\n", encoding="utf-8")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "live Qwen conflict demo base")
    return project


def _enabled_tasks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8").strip()
    prefix = "enabled_tasks="
    if not text.startswith(prefix) or "\n" in text:
        raise RuntimeError(
            f"{path} must contain exactly one enabled_tasks line, got: {text!r}"
        )
    values = [item.strip() for item in text[len(prefix):].split(",") if item.strip()]
    if not values:
        raise RuntimeError(f"{path} contains an empty enabled_tasks list")
    if len(values) != len(set(values)):
        raise RuntimeError(f"{path} contains duplicate enabled_tasks entries: {values}")
    return values


def _task_goal(marker: str) -> str:
    return (
        f"LIVE WORKTREE CONFLICT TEST - {marker}. "
        "Edit only shared.txt. The file is a single comma-separated enabled_tasks list. "
        f"Add {marker} exactly once while preserving every entry already present. "
        "Do not remove BASE. Do not modify any other file. Do not run Git commands. "
        "Do not create tests, docs, config, helper files, or workflow files; shared.txt is the only deliverable. "
        f"On the initial base, the expected logical entries are BASE and {marker}. "
        "If this same task is later replayed in a merge-recovery workspace where another "
        "entry such as TASK_A already exists, preserve that newer entry and add this task's "
        "entry rather than overwriting the latest target."
    )


def _create_task(tasks: TaskService, project: Path, marker: str) -> dict[str, Any]:
    return tasks.create(
        project,
        {
            "title": f"Live Qwen {marker}",
            "items": [
                {
                    "title": f"Add {marker}",
                    "prompt": _task_goal(marker),
                    "workflow": str(RALPHY_WORKFLOW),
                    "project": str(project),
                    "workspace": "main",
                }
            ],
        },
        request_id=f"create-live-qwen-{marker.lower()}",
    )


def _runner_command(
    project: Path,
    goal: str,
    *,
    qwen_command: str,
    timeout: int,
) -> list[str]:
    return [
        sys.executable,
        str(RUNNER),
        "--goal",
        goal,
        "--project-root",
        str(project),
        "--workflow",
        str(RALPHY_WORKFLOW),
        "--backend",
        "qwen",
        "--command",
        qwen_command,
        "--force-new",
        "--stage-retries",
        "1",
        "--max-cycles",
        "2",
        "--final-ai-validations",
        "1",
        "--final-ai-required-passes",
        "1",
        "--retry-delay",
        "1",
        "--retry-max-delay",
        "5",
        "--agent-timeout",
        str(timeout),
        "--planning-timeout",
        str(timeout),
        "--validator-timeout",
        str(timeout),
        "--json-events",
        "--no-ui-project-register",
    ]


def run_live_demo(
    base: Path,
    *,
    qwen_command: str,
    timeout: int = 300,
    verbose: bool = True,
) -> dict[str, Any]:
    base = Path(base).expanduser().resolve()
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    logs = base / "logs"
    logs.mkdir()
    project = _init_project(base)

    tasks = TaskService(workflow_requirements=lambda _p, _w: {"exists": True})
    task_a = _create_task(tasks, project, "TASK_A")
    task_b = _create_task(tasks, project, "TASK_B")

    runtimes: dict[Path, dict[str, Any]] = {}
    runtime_lock = threading.Lock()
    initial_barrier = threading.Barrier(2)
    launches: list[dict[str, Any]] = []
    launch_counter = {"recovery": 0}

    def launch(runtime_project: Path, goal: str | None, **kwargs: Any) -> None:
        runtime_project = Path(runtime_project).resolve()
        goal_text = str(goal or "")
        is_recovery = goal_text.startswith("Merge-repair task only.")
        if is_recovery:
            launch_counter["recovery"] += 1
            label = f"recovery-{launch_counter['recovery']}"
        elif "TASK_A" in goal_text:
            label = "task-a"
        else:
            label = "task-b"
        log_path = logs / f"{label}.log"

        with runtime_lock:
            runtimes[runtime_project] = {
                "running": True,
                "launching": False,
                "completed": False,
                "resumable": False,
                "stale": False,
                "has_state": True,
                "actions": {},
            }
            launches.append(
                {
                    "label": label,
                    "project": str(runtime_project),
                    "goal": goal_text,
                    "workflow": str(kwargs.get("workflow") or ""),
                    "log": str(log_path),
                }
            )

        if not is_recovery:
            initial_barrier.wait(timeout=60)

        command = _runner_command(
            runtime_project,
            goal_text,
            qwen_command=qwen_command,
            timeout=timeout,
        )
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=max(timeout * 2, 600),
        )
        log_path.write_text(completed.stdout, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            tail = completed.stdout[-12000:]
            with runtime_lock:
                runtimes[runtime_project] = {
                    "running": False,
                    "launching": False,
                    "completed": False,
                    "resumable": False,
                    "stale": False,
                    "has_state": True,
                    "last_error": tail,
                    "actions": {},
                }
            raise RuntimeError(
                f"{label} Qwen Runner failed with exit code {completed.returncode}. "
                f"Log: {log_path}\n{tail}"
            )

        with runtime_lock:
            runtimes[runtime_project] = {
                "running": False,
                "launching": False,
                "completed": True,
                "resumable": False,
                "stale": False,
                "has_state": True,
                "actions": {},
            }

    def read_runtime(runtime_project: Path) -> dict[str, Any]:
        with runtime_lock:
            return dict(
                runtimes.get(
                    Path(runtime_project).resolve(),
                    {
                        "running": False,
                        "launching": False,
                        "completed": False,
                        "resumable": False,
                        "stale": False,
                        "has_state": False,
                        "actions": {},
                    },
                )
            )

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
            "reasoning": "medium",
            "workflow": str(RALPHY_WORKFLOW),
        },
        backend_default=lambda _project: "qwen",
        resolve_workflow=lambda _project, selected: Path(selected),
        launch=launch,
        read_runtime=read_runtime,
        stop_runtime=lambda _project: None,
        resume_runtime=lambda _project: None,
        validate_merge=lambda _project, _goal, **_kwargs: "PASS",
        workspace_manager=WorkspaceManager(worktree_root=base / "worktrees"),
        auto_watch=False,
    )

    if verbose:
        print(f"[1/8] Live project: {project}")
        print("[2/8] Starting Task A and Task B concurrently with real Qwen...")

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(
            service.start,
            project,
            task_a["task_id"],
            request_id="run-live-qwen-task-a",
        )
        future_b = pool.submit(
            service.start,
            project,
            task_b["task_id"],
            request_id="run-live-qwen-task-b",
        )
        started_a = future_a.result(timeout=max(timeout * 3, 900))
        started_b = future_b.result(timeout=max(timeout * 3, 900))

    root_a = Path(started_a["run"]["workspace"]["project_root"])
    root_b = Path(started_b["run"]["workspace"]["project_root"])
    if root_a == root_b or root_a == project or root_b == project:
        raise RuntimeError("Concurrent Tasks did not receive two isolated worktrees")
    if started_a["run"]["workspace"]["task_base_sha"] != started_b["run"]["workspace"]["task_base_sha"]:
        raise RuntimeError("Concurrent Tasks did not start from the same target HEAD")

    values_a = set(_enabled_tasks(root_a / "shared.txt"))
    values_b = set(_enabled_tasks(root_b / "shared.txt"))
    if values_a != {"BASE", "TASK_A"}:
        raise RuntimeError(
            f"Task A Qwen output is unexpected: {sorted(values_a)}. "
            f"See {logs / 'task-a.log'}"
        )
    if values_b != {"BASE", "TASK_B"}:
        raise RuntimeError(
            f"Task B Qwen output is unexpected: {sorted(values_b)}. "
            f"See {logs / 'task-b.log'}"
        )
    if set(_enabled_tasks(project / "shared.txt")) != {"BASE"}:
        raise RuntimeError("Target Main was modified before delivery")

    if verbose:
        print(f"[3/8] Task A worktree: {root_a}")
        print(f"[3/8] Task B worktree: {root_b}")
        print("[4/8] Both Qwen Runners finished; Main is still untouched.")
        print("[5/8] Merging Task A...")

    closed_a = service.reconcile(project, task_a["task_id"])
    if closed_a["status"] != "closed" or closed_a["run"]["phase"] != "merged":
        raise RuntimeError(f"Task A did not merge cleanly: {json.dumps(closed_a, ensure_ascii=False)}")
    if set(_enabled_tasks(project / "shared.txt")) != {"BASE", "TASK_A"}:
        raise RuntimeError("Task A merge did not update Main correctly")

    if verbose:
        print("[6/8] Task A merged. Reconciling Task B; a real Git conflict is expected...")

    recovering_b = service.reconcile(project, task_b["task_id"])
    if recovering_b["status"] != "ongoing" or recovering_b["run"]["phase"] != "conflict_recovery":
        raise RuntimeError(
            "Task B did not enter automatic conflict recovery: "
            + json.dumps(recovering_b, ensure_ascii=False)
        )
    result = recovering_b["run"].get("workspace_result") or {}
    failure = result.get("last_merge_failure") or result.get("merge") or {}
    conflict_files = failure.get("conflict_files") or []
    if "shared.txt" not in conflict_files:
        raise RuntimeError(f"Expected shared.txt conflict, got: {conflict_files}")

    recovery = result.get("recovery") or {}
    recovery_root = Path((recovery.get("workspace") or {}).get("project_root") or "")
    if not recovery_root.is_dir():
        raise RuntimeError("Automatic recovery worktree was not created")
    recovery_values = set(_enabled_tasks(recovery_root / "shared.txt"))
    if recovery_values != {"BASE", "TASK_A", "TASK_B"}:
        raise RuntimeError(
            f"Real Qwen recovery did not preserve A and integrate B: {sorted(recovery_values)}. "
            f"See {logs / 'recovery-1.log'}"
        )

    if verbose:
        print(f"[7/8] Qwen recovery worktree: {recovery_root}")
        print("[7/8] Qwen preserved Task A and integrated Task B. Finalizing recovery merge...")

    closed_b = service.reconcile(project, task_b["task_id"])
    if closed_b["status"] != "closed" or closed_b["run"]["phase"] != "merged":
        raise RuntimeError(
            "Recovered Task B did not merge: "
            + json.dumps(closed_b, ensure_ascii=False)
        )

    final_values = set(_enabled_tasks(project / "shared.txt"))
    if final_values != {"BASE", "TASK_A", "TASK_B"}:
        raise RuntimeError(f"Final Main content is wrong: {sorted(final_values)}")
    source_status = _source_status_ignoring_runner_runtime(project)
    if source_status:
        raise RuntimeError(
            "Final Main has uncommitted source changes outside runner-owned runtime state:\n"
            + source_status
        )
    merge_count = int(_git(project, "rev-list", "--merges", "--count", "HEAD"))
    if merge_count < 2:
        raise RuntimeError(f"Expected at least two merge commits, got {merge_count}")

    history = _git(project, "--no-pager", "log", "--graph", "--oneline", "--decorate", "-12")
    final_text = (project / "shared.txt").read_text(encoding="utf-8")

    if verbose:
        print("[8/8] PASS - real Qwen conflict recovery merged successfully.")
        print("\nFinal shared.txt:")
        print(final_text, end="")
        print("\nGit history:")
        print(history)
        print(f"\nLogs: {logs}")
        print(f"Demo workspace retained at: {base}")

    return {
        "project": str(project),
        "task_a_worktree": str(root_a),
        "task_b_worktree": str(root_b),
        "recovery_worktree": str(recovery_root),
        "conflict_files": list(conflict_files),
        "final_entries": sorted(final_values),
        "merge_count": merge_count,
        "history": history,
        "logs": str(logs),
        "launches": launches,
        "source_status": source_status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run two concurrent real-Qwen Runner Tasks in isolated worktrees, "
            "force a Git conflict, then prove TaskRunService auto-recovers with Qwen."
        )
    )
    parser.add_argument(
        "--root",
        help="Demo workspace. Default: a retained directory under the system temp folder.",
    )
    parser.add_argument(
        "--qwen-command",
        default="qwen.cmd" if os.name == "nt" else "qwen",
        help="Qwen CLI command passed to Runner.",
    )
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args(argv)

    created_temp = not bool(args.root)
    base = (
        Path(args.root).expanduser().resolve()
        if args.root
        else Path(tempfile.mkdtemp(prefix="ai-task-runner-live-qwen-conflict-"))
    )
    try:
        result = run_live_demo(
            base,
            qwen_command=str(args.qwen_command),
            timeout=max(60, int(args.timeout)),
            verbose=not args.json,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"[INFO] Demo workspace retained at: {base}", file=sys.stderr)
        return 1
    finally:
        if args.cleanup and base.exists():
            shutil.rmtree(base, ignore_errors=True)
        elif created_temp:
            # Retain by default for manual inspection of worktrees and logs.
            pass


if __name__ == "__main__":
    raise SystemExit(main())
