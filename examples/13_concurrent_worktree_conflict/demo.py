#!/usr/bin/env python3
"""Real Runner + isolated worktree + merge-conflict recovery demo."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = Path(__file__).resolve().parent
RUNNER = ROOT / "ai_task_runner.py"
AGENT = EXAMPLE / "mock_agent.py"
WORKFLOW_SOURCE = EXAMPLE / "workflow.yaml"

sys.path.insert(0, str(ROOT))
from workspace import MergeManager, WorkspaceManager  # noqa: E402


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({result.returncode}):\n"
            f"{result.stderr or result.stdout}"
        )
    return result.stdout.strip()


def _init_project(base: Path) -> Path:
    project = base / "project"
    project.mkdir(parents=True)
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Concurrent Worktree Demo")
    _git(project, "config", "user.email", "concurrent-demo@example.invalid")
    (project / "shared.txt").write_text("BASE\n", encoding="utf-8")
    shutil.copy2(WORKFLOW_SOURCE, project / "workflow.yaml")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "demo base")
    return project


def _runner_command(project_root: Path, mode: str, sleep_seconds: float) -> list[str]:
    python = Path(sys.executable).resolve().as_posix()
    agent = AGENT.resolve().as_posix()
    backend_command = (
        f'"{python}" "{agent}" '
        f"--demo-mode {mode} --sleep {max(0.0, sleep_seconds):.3f}"
    )
    return [
        sys.executable,
        str(RUNNER),
        "--goal",
        f"Concurrent worktree demo: {mode}",
        "--project-root",
        str(project_root),
        "--workflow",
        str(project_root / "workflow.yaml"),
        "--backend",
        "qwen",
        "--command",
        backend_command,
        "--stage-retries",
        "0",
        "--retry-delay",
        "0",
        "--retry-max-delay",
        "0",
        "--agent-timeout",
        "60",
        "--agent-idle-after-change-timeout",
        "0",
        "--no-ui-project-register",
        "--force-new",
    ]


def _start_runner(project_root: Path, mode: str, sleep_seconds: float) -> subprocess.Popen[str]:
    return subprocess.Popen(
        _runner_command(project_root, mode, sleep_seconds),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _finish_runner(process: subprocess.Popen[str], label: str, timeout: float = 90) -> str:
    output, _ = process.communicate(timeout=timeout)
    if process.returncode != 0:
        raise RuntimeError(
            f"{label} Runner failed with exit {process.returncode}:\n{output}"
        )
    return output


def run_demo(
    base: Path,
    *,
    sleep_seconds: float = 0.5,
    verbose: bool = True,
) -> dict[str, Any]:
    base = Path(base).expanduser().resolve()
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    project = _init_project(base)

    manager = WorkspaceManager(worktree_root=base / "worktrees")
    settings = {
        "auto_workspace_policy": "always-main",
        "allow_concurrent_main_tasks": True,
    }
    task_a = manager.prepare(
        project,
        task_id="task-" + "a" * 32,
        run_number=1,
        requested_mode="main",
        execution_settings=settings,
        main_running=False,
    )
    task_b = manager.prepare(
        project,
        task_id="task-" + "b" * 32,
        run_number=1,
        requested_mode="main",
        execution_settings=settings,
        main_running=True,
    )
    if task_a.worktree_path == task_b.worktree_path:
        raise AssertionError("concurrent Tasks must use distinct worktrees")
    if task_a.task_base_sha != task_b.task_base_sha:
        raise AssertionError("demo Tasks must start from the same captured target HEAD")

    if verbose:
        print(f"[1] Project: {project}")
        print(f"[2] Task A worktree: {task_a.worktree_path}")
        print(f"[2] Task B worktree: {task_b.worktree_path}")
        print("[3] Starting both real Runner subprocesses concurrently...")

    process_a = _start_runner(task_a.project_root, "task-a", sleep_seconds)
    process_b = _start_runner(task_b.project_root, "task-b", sleep_seconds)
    time.sleep(min(0.15, max(0.02, sleep_seconds / 3 if sleep_seconds else 0.02)))
    overlapped = process_a.poll() is None and process_b.poll() is None

    output_a = _finish_runner(process_a, "Task A")
    output_b = _finish_runner(process_b, "Task B")
    if not overlapped:
        raise AssertionError("Runner processes did not overlap; increase --sleep for this environment")
    if (task_a.project_root / "shared.txt").read_text(encoding="utf-8") != "TASK-A\n":
        raise AssertionError("Task A Runner output is incorrect")
    if (task_b.project_root / "shared.txt").read_text(encoding="utf-8") != "TASK-B\n":
        raise AssertionError("Task B Runner output is incorrect")

    snapshot_a = manager.snapshot_result(
        task_a,
        excluded_paths=(task_a.project_root / ".ai-task-runner",),
    )
    snapshot_b = manager.snapshot_result(
        task_b,
        excluded_paths=(task_b.project_root / ".ai-task-runner",),
    )

    merger = MergeManager()
    merged_a = merger.merge(task_a, snapshot_a)
    if merged_a.status != "merged":
        raise AssertionError(f"Task A merge failed: {merged_a.as_dict()}")
    if verbose:
        print(f"[4] Task A merge: {merged_a.status} (queue seq {merged_a.merge_queue_seq})")

    conflicted_b = merger.merge(task_b, snapshot_b, validate=lambda _project: "PASS")
    if conflicted_b.status != "conflict" or "shared.txt" not in conflicted_b.conflict_files:
        raise AssertionError(f"Task B should conflict on shared.txt: {conflicted_b.as_dict()}")
    if verbose:
        print(
            "[5] Task B merge intentionally conflicted: "
            + ", ".join(conflicted_b.conflict_files)
        )

    recovery = manager.prepare_recovery(task_b, snapshot_b, failure_number=1)
    patch = manager.recovery_patch(task_b, snapshot_b)
    patch_root = recovery.project_root / ".ai-task-runner" / "ui" / "merge-recovery"
    patch_root.mkdir(parents=True, exist_ok=True)
    patch_path = patch_root / f"{task_b.task_id}-r{task_b.run_number}-f1.patch"
    patch_path.write_text(patch, encoding="utf-8")
    if verbose:
        print(f"[6] Recovery worktree: {recovery.worktree_path}")
        print(f"[6] Recovery patch: {patch_path}")
        print("[7] Running real Runner again to repair the conflict...")

    recovery_process = _start_runner(recovery.project_root, "recovery", 0.0)
    recovery_output = _finish_runner(recovery_process, "Recovery")
    expected = "TASK-A\nTASK-B\n"
    if (recovery.project_root / "shared.txt").read_text(encoding="utf-8") != expected:
        raise AssertionError("recovery Runner did not preserve A and apply B")

    recovery_snapshot = manager.snapshot_result(
        recovery,
        excluded_paths=(recovery.project_root / ".ai-task-runner",),
    )
    merged_b = merger.merge(recovery, recovery_snapshot, validate=lambda _project: "PASS")
    if merged_b.status != "merged":
        raise AssertionError(f"Recovery merge failed: {merged_b.as_dict()}")

    final_text = (project / "shared.txt").read_text(encoding="utf-8")
    if final_text != expected:
        raise AssertionError(f"final merged content is incorrect: {final_text!r}")
    if _git(project, "status", "--porcelain"):
        raise AssertionError("target Project is dirty after demo")
    head = _git(project, "rev-parse", "HEAD")

    if verbose:
        print(f"[8] Recovery merge: {merged_b.status} (queue seq {merged_b.merge_queue_seq})")
        print("[9] FINAL shared.txt:")
        print(final_text, end="")
        print(f"[PASS] Final HEAD: {head}")
        print("[PASS] Two concurrent Runners -> isolated worktrees -> conflict -> Runner recovery -> merged.")

    return {
        "project": str(project),
        "task_a_worktree": str(task_a.worktree_path),
        "task_b_worktree": str(task_b.worktree_path),
        "recovery_worktree": str(recovery.worktree_path),
        "runners_overlapped": overlapped,
        "task_a_merge": merged_a.as_dict(),
        "task_b_conflict": conflicted_b.as_dict(),
        "recovery_merge": merged_b.as_dict(),
        "final_text": final_text,
        "final_head": head,
        "runner_output_a": output_a,
        "runner_output_b": output_b,
        "runner_output_recovery": recovery_output,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        help="Demo workspace. Default: a new directory under the system temp folder.",
    )
    parser.add_argument("--sleep", type=float, default=0.6, help="Mock agent delay used to make Runner overlap visible.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cleanup", action="store_true", help="Delete the demo workspace after PASS.")
    args = parser.parse_args()

    created_temp = not bool(args.root)
    base = (
        Path(args.root).expanduser().resolve()
        if args.root
        else Path(tempfile.mkdtemp(prefix="ai-task-runner-worktree-conflict-"))
    )
    try:
        result = run_demo(base, sleep_seconds=args.sleep, verbose=not args.json)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif not args.cleanup:
            print(f"[INFO] Demo files retained at: {base}")
        return 0
    finally:
        if args.cleanup and base.exists():
            shutil.rmtree(base, ignore_errors=True)
        elif created_temp:
            # Default BAT/demo behavior intentionally retains the temp repo so the
            # user can inspect branches, worktrees and merge commits afterward.
            pass


if __name__ == "__main__":
    raise SystemExit(main())
