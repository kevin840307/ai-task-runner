from __future__ import annotations

import json
import subprocess
import sys
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
    assert "AI Task Runner merge" in graph


def test_windows_demo_bat_executes_the_same_production_demo() -> None:
    text = BAT.read_text(encoding="utf-8")
    assert "13_concurrent_worktree_conflict\\demo.py" in text
    assert "%*" in text
    assert "exit /b %RC%" in text
