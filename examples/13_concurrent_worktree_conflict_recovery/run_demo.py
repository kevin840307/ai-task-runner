#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from workspace import MergeManager, WorkspaceManager


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUNNER = ROOT / "ai_task_runner.py"
MOCK_AGENT = HERE / "mock_agent.py"
WORKFLOW = HERE / "workflow.yaml"


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


def _runner_command(project_root: Path, variant: str) -> list[str]:
    command = f'"{sys.executable}" "{MOCK_AGENT}"'
    return [
        sys.executable,
        str(RUNNER),
        "--goal",
        f"Concurrent demo Task {variant}: update app.txt",
        "--project-root",
        str(project_root),
        "--workflow",
        str(project_root / "workflow.yaml"),
        "--backend",
        "qwen",
        "--command",
        command,
        "--force-new",
        "--stage-retries",
        "0",
        "--retry-delay",
        "0",
        "--retry-max-delay",
        "0",
        "--agent-timeout",
        "30",
    ]


def _start_runner(project_root: Path, variant: str, log_path: Path) -> tuple[subprocess.Popen[str], object]:
    env = os.environ.copy()
    env["CONCURRENT_DEMO_VARIANT"] = variant
    stream = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        _runner_command(project_root, variant),
        cwd=ROOT,
        env=env,
        text=True,
        stdout=stream,
        stderr=subprocess.STDOUT,
    )
    return process, stream


def _wait_runner(process: subprocess.Popen[str], stream: object, log_path: Path, label: str) -> None:
    try:
        code = process.wait(timeout=90)
    finally:
        stream.close()
    if code != 0:
        output = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        raise RuntimeError(f"{label} Runner failed with exit code {code}\n{output}")


def _run_recovery(project_root: Path, log_path: Path) -> None:
    env = os.environ.copy()
    env["CONCURRENT_DEMO_VARIANT"] = "RECOVERY"
    command = _runner_command(project_root, "RECOVERY")
    command[command.index("--goal") + 1] = (
        "Merge-repair task only. Preserve the latest target content from Task A "
        "and integrate Task B into app.txt. The final file must contain both "
        "'task-a: enabled' and 'task-b: enabled'."
    )
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=90,
    )
    log_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(
            f"Recovery Runner failed with exit code {result.returncode}\n{result.stdout}"
        )


def _initialise_demo_repo(project: Path) -> None:
    project.mkdir(parents=True)
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "AI Task Runner Demo")
    _git(project, "config", "user.email", "demo@example.invalid")
    (project / "app.txt").write_text("base\n", encoding="utf-8")
    shutil.copy2(WORKFLOW, project / "workflow.yaml")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "demo base")


def run_demo(output_root: Path) -> dict[str, str]:
    output_root = output_root.expanduser().resolve()
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    project = output_root / "project"
    worktrees = output_root / "worktrees"
    logs = output_root / "logs"
    logs.mkdir()
    _initialise_demo_repo(project)

    manager_a = WorkspaceManager(worktree_root=worktrees)
    manager_b = WorkspaceManager(worktree_root=worktrees)
    settings = {
        "auto_workspace_policy": "always-main",
        "allow_concurrent_main_tasks": True,
    }
    task_a = manager_a.prepare(
        project,
        task_id="task-" + "a" * 32,
        run_number=1,
        requested_mode="main",
        execution_settings=settings,
        main_running=False,
    )
    task_b = manager_b.prepare(
        project,
        task_id="task-" + "b" * 32,
        run_number=1,
        requested_mode="main",
        execution_settings=settings,
        main_running=True,
    )

    if task_a.project_root == task_b.project_root:
        raise RuntimeError("Tasks did not receive isolated worktrees")
    if task_a.task_base_sha != task_b.task_base_sha:
        raise RuntimeError("Tasks were not prepared from the same target HEAD")

    print(f"[1/7] Task A worktree: {task_a.project_root}")
    print(f"[1/7] Task B worktree: {task_b.project_root}")
    print("[2/7] Starting both production Runner processes concurrently...")

    process_a, stream_a = _start_runner(task_a.project_root, "A", logs / "task-a.log")
    process_b, stream_b = _start_runner(task_b.project_root, "B", logs / "task-b.log")
    _wait_runner(process_a, stream_a, logs / "task-a.log", "Task A")
    _wait_runner(process_b, stream_b, logs / "task-b.log", "Task B")

    print("[3/7] Both Runners completed. Snapshotting Task branches...")
    snapshot_a = manager_a.snapshot_result(
        task_a,
        excluded_paths=(task_a.project_root / ".ai-task-runner",),
    )
    snapshot_b = manager_b.snapshot_result(
        task_b,
        excluded_paths=(task_b.project_root / ".ai-task-runner",),
    )

    merge_manager = MergeManager()
    merged_a = merge_manager.merge(task_a, snapshot_a)
    if merged_a.status != "merged":
        raise RuntimeError(f"Task A merge was not successful: {merged_a.as_dict()}")
    if "task-a: enabled" not in (project / "app.txt").read_text(encoding="utf-8"):
        raise RuntimeError("Task A content did not reach target")

    print("[4/7] Task A merged. Merging Task B against the advanced target...")
    conflicted_b = merge_manager.merge(
        task_b,
        snapshot_b,
        validate=lambda _project: "PASS",
    )
    if conflicted_b.status != "conflict":
        raise RuntimeError(
            "Expected Task B to conflict after Task A advanced target, "
            f"got: {conflicted_b.as_dict()}"
        )
    if "app.txt" not in conflicted_b.conflict_files:
        raise RuntimeError(
            f"Expected app.txt conflict, got: {conflicted_b.conflict_files}"
        )
    print(f"[5/7] Expected conflict detected: {', '.join(conflicted_b.conflict_files)}")

    recovery = manager_b.prepare_recovery(
        task_b,
        snapshot_b,
        failure_number=1,
    )
    patch_text = manager_b.recovery_patch(task_b, snapshot_b)
    patch_dir = recovery.project_root / ".ai-task-runner" / "recovery"
    patch_dir.mkdir(parents=True, exist_ok=True)
    patch_path = patch_dir / "task-b.patch"
    patch_path.write_text(patch_text, encoding="utf-8")

    print(f"[6/7] Recovery worktree: {recovery.project_root}")
    print("[6/7] Running production Runner to resolve the merge conflict...")
    _run_recovery(recovery.project_root, logs / "recovery.log")
    recovery_snapshot = manager_b.snapshot_result(
        recovery,
        excluded_paths=(recovery.project_root / ".ai-task-runner",),
    )
    recovered_merge = merge_manager.merge(
        recovery,
        recovery_snapshot,
        validate=lambda _project: "PASS",
    )
    if recovered_merge.status != "merged":
        raise RuntimeError(
            f"Recovery merge was not successful: {recovered_merge.as_dict()}"
        )

    final_text = (project / "app.txt").read_text(encoding="utf-8")
    if "task-a: enabled" not in final_text or "task-b: enabled" not in final_text:
        raise RuntimeError(f"Final app.txt did not preserve both Tasks:\n{final_text}")
    if _git(project, "status", "--porcelain"):
        raise RuntimeError("Final target repository is dirty")
    merge_head = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
        cwd=project,
        text=True,
        capture_output=True,
    )
    if merge_head.returncode == 0:
        raise RuntimeError("MERGE_HEAD still exists after recovery")

    history = _git(project, "--no-pager", "log", "--oneline", "--graph", "--decorate", "-8")
    print("[7/7] PASS: conflict was detected, recovered by Runner, and merged.")
    print("\nFinal app.txt:")
    print(final_text.rstrip())
    print("\nGit history:")
    print(history)
    print(f"\nDemo workspace kept at: {output_root}")
    print(f"Logs: {logs}")

    return {
        "project": str(project),
        "task_a_worktree": str(task_a.project_root),
        "task_b_worktree": str(task_b.project_root),
        "recovery_worktree": str(recovery.project_root),
        "final_text": final_text,
        "history": history,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run two concurrent Runner Tasks in worktrees and auto-recover a real Git merge conflict."
    )
    parser.add_argument(
        "--output",
        default=str(Path(os.environ.get("TEMP", ".")) / "ai-task-runner-concurrent-conflict-demo"),
    )
    args = parser.parse_args(argv)
    try:
        run_demo(Path(args.output))
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
