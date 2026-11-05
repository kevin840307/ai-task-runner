from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "13_concurrent_worktree_conflict" / "demo.py"
BAT = ROOT / "examples" / "13_concurrent_worktree_conflict" / "run_example.bat"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def test_concurrent_real_runners_conflict_then_recovery_merges_cleanly(tmp_path: Path) -> None:
    demo_root = tmp_path / "concurrent-demo"
    result = subprocess.run(
        [
            sys.executable,
            str(DEMO),
            "--root",
            str(demo_root),
            "--sleep",
            "0.35",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    payload = json.loads(result.stdout)

    assert payload["runners_overlapped"] is True
    assert Path(payload["task_a_worktree"]).resolve() != Path(payload["task_b_worktree"]).resolve()
    assert Path(payload["recovery_worktree"]).resolve() not in {
        Path(payload["task_a_worktree"]).resolve(),
        Path(payload["task_b_worktree"]).resolve(),
    }

    assert payload["task_a_merge"]["status"] == "merged"
    assert payload["task_b_conflict"]["status"] == "conflict"
    assert payload["task_b_conflict"]["real_merge_failure"] is True
    assert payload["task_b_conflict"]["conflict_files"] == ["shared.txt"]
    assert payload["recovery_merge"]["status"] == "merged"
    assert payload["task_b_conflict"]["merge_queue_seq"] == payload["recovery_merge"]["merge_queue_seq"]
    assert payload["final_text"] == "TASK-A\nTASK-B\n"

    project = Path(payload["project"])
    assert (project / "shared.txt").read_text(encoding="utf-8") == "TASK-A\nTASK-B\n"
    assert _git(project, "status", "--porcelain") == ""
    graph = _git(project, "log", "--graph", "--oneline", "--all", "-12")
    merge_count = int(_git(project, "rev-list", "--merges", "--count", "HEAD"))
    assert merge_count == 2
    assert graph.count("Merge task-") >= 2


def test_windows_demo_bat_executes_the_same_production_demo() -> None:
    text = BAT.read_text(encoding="utf-8")
    assert "13_concurrent_worktree_conflict\\demo.py" in text
    assert "%*" in text
    assert "exit /b %RC%" in text

def test_two_projects_run_concurrent_runner_worktree_recovery_without_cross_repo_state(
    tmp_path: Path,
) -> None:
    """Two Projects concurrently run the full deterministic conflict demo.

    Each Project launches two real Runner subprocesses plus one recovery Runner,
    so this exercises repository-scoped worktree/merge locks and queues under
    cross-Project concurrency without requiring a live model.
    """

    def run_project(name: str) -> dict:
        demo_root = tmp_path / name
        completed = subprocess.run(
            [
                sys.executable,
                str(DEMO),
                "--root",
                str(demo_root),
                "--sleep",
                "0.35",
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=240,
        )
        assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
        return json.loads(completed.stdout)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(run_project, "project-a-demo")
        future_b = pool.submit(run_project, "project-b-demo")
        first = future_a.result(timeout=300)
        second = future_b.result(timeout=300)

    assert Path(first["project"]).resolve() != Path(second["project"]).resolve()
    for payload in (first, second):
        assert payload["runners_overlapped"] is True
        assert payload["task_a_merge"]["status"] == "merged"
        assert payload["task_b_conflict"]["status"] == "conflict"
        assert payload["task_b_conflict"]["conflict_files"] == ["shared.txt"]
        assert payload["recovery_merge"]["status"] == "merged"
        assert payload["final_text"] == "TASK-A\nTASK-B\n"
        assert payload["task_b_conflict"]["merge_queue_seq"] == payload["recovery_merge"]["merge_queue_seq"]

        project = Path(payload["project"])
        assert project.joinpath("shared.txt").read_text(encoding="utf-8") == "TASK-A\nTASK-B\n"
        assert _git(project, "status", "--porcelain") == ""
        assert int(_git(project, "rev-list", "--merges", "--count", "HEAD")) == 2

    # Queue sequence numbers are repository-scoped; both independent Projects
    # may own their own first delivery sequence without cross-contamination.
    assert first["task_a_merge"]["merge_queue_seq"] == 1
    assert second["task_a_merge"]["merge_queue_seq"] == 1

