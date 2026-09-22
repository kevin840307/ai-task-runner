from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from ui.server import UIServer

ROOT = Path(__file__).resolve().parents[1]


def _post(base: str, path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _make_ui_repo(root: Path) -> None:
    (root / "ui" / "data").mkdir(parents=True)
    (root / "ui" / "static").mkdir(parents=True)
    (root / "ui" / "data" / "projects.json").write_text("[]", encoding="utf-8")
    (root / "ui" / "static" / "index.html").write_text("UI", encoding="utf-8")


def test_live_http_project_add_rename_remove_roundtrip(tmp_path: Path) -> None:
    """Exercise real localhost HTTP + real projects.json persistence, without mocks."""
    repo = tmp_path / "runner-repo"
    _make_ui_repo(repo)
    project = tmp_path / "ProjectA"
    project.mkdir()

    server = UIServer(repo, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        added = _post(base, "/api/projects/add", {"path": str(project) + os.sep})
        assert Path(added["path"]).resolve() == project.resolve()

        projects = _get(base, "/api/projects")["projects"]
        assert len(projects) == 1
        assert Path(projects[0]["path"]).resolve() == project.resolve()

        # Equivalent path spelling must not produce a second sidebar row.
        _post(base, "/api/projects/add", {"path": str(project)})
        assert len(_get(base, "/api/projects")["projects"]) == 1

        renamed = _post(base, "/api/projects/rename", {"path": str(project), "name": "Live Project"})
        assert renamed["name"] == "Live Project"
        assert _get(base, "/api/projects")["projects"][0]["name"] == "Live Project"

        _post(base, "/api/projects/remove", {"path": str(project) + os.sep})
        assert _get(base, "/api/projects")["projects"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_live_cross_process_project_registration_preserves_all_projects(tmp_path: Path) -> None:
    """Two real Python processes update the same registry concurrently."""
    repo = tmp_path / "runner-repo"
    _make_ui_repo(repo)
    projects = [tmp_path / f"Project{i}" for i in range(6)]
    for project in projects:
        project.mkdir()

    code = (
        "from pathlib import Path; "
        "from runner.ui_projects import register_ui_project; "
        "import sys; "
        "register_ui_project(Path(sys.argv[2]), project_name=sys.argv[3], repo_root=Path(sys.argv[1]))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(repo), str(project), f"Live {index}"],
            cwd=ROOT,
            env=env,
        )
        for index, project in enumerate(projects)
    ]
    assert [proc.wait(timeout=10) for proc in procs] == [0] * len(procs)

    rows = json.loads((repo / "ui" / "data" / "projects.json").read_text(encoding="utf-8"))
    assert len(rows) == len(projects)
    by_path = {os.path.normcase(os.path.abspath(row["path"])): row["name"] for row in rows}
    for index, project in enumerate(projects):
        assert by_path[os.path.normcase(os.path.abspath(str(project)))] == f"Live {index}"


def test_live_cli_project_name_plumbing_registers_display_name(tmp_path: Path) -> None:
    """Parse the real CLI in a subprocess and feed its RunRequest value into registration."""
    repo = tmp_path / "runner-repo"
    _make_ui_repo(repo)
    project = tmp_path / "NamedProject"
    project.mkdir()

    code = r'''
from pathlib import Path
import sys
from ai_task_runner import parser
from runner.api import RunRequest
from runner.ui_projects import register_ui_project
args = parser().parse_args([
    "--goal", "x",
    "--project-root", sys.argv[2],
    "--project-name", "CLI Live Name",
    "--validator", "ai",
])
request = RunRequest.from_namespace(args)
register_ui_project(request.project_root, project_name=request.project_name, repo_root=Path(sys.argv[1]))
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", code, str(repo), str(project)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    rows = json.loads((repo / "ui" / "data" / "projects.json").read_text(encoding="utf-8"))
    assert rows == [{"name": "CLI Live Name", "path": str(project.resolve())}]


def test_live_yaml_project_name_overrides_outer_default(tmp_path: Path) -> None:
    """Load a real task YAML in a subprocess and verify child display-name precedence."""
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: x\n  validator: ai\n  project_name: YAML Live Name\n",
        encoding="utf-8",
    )
    code = r'''
from pathlib import Path
import sys
from runner.api import RunRequest
from runner.script_loader import load_yaml_script
from runner.script_runner import build_script_item_config
outer = RunRequest(project_root=sys.argv[2], project_name="Outer Name", script=sys.argv[1], validator="ai").normalized_config()
item = load_yaml_script(Path(sys.argv[1]))[0]
child = build_script_item_config(outer, item, 1)
print(child.project_name)
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", code, str(script), str(tmp_path)],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "YAML Live Name"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required for live worktree lifecycle test")
def test_live_worktree_clean_removes_stale_jobs_and_rejects_unrelated_directory(tmp_path: Path) -> None:
    """Use a real git repository/worktree instead of mocking git commands."""
    repo = tmp_path / "TestProject"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "live@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Live Test"], cwd=repo, check=True)
    task_yaml = repo / "tasks.yaml"
    task_yaml.write_text("- prompt: one\n  validator: ai\n- prompt: two\n  validator: ai\n- prompt: three\n  validator: ai\n", encoding="utf-8")
    (repo / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=repo, check=True, capture_output=True)

    config = tmp_path / "launcher.yaml"
    config.write_text(
        "\n".join([
            f"repo: {repo}",
            f"worktree_root: {tmp_path}",
            "concurrency: 3",
            "base_branch: HEAD",
            "task_yaml: tasks.yaml",
            f"runner: {ROOT / 'ai_task_runner.py'}",
        ]) + "\n",
        encoding="utf-8",
    )
    launcher = ROOT / "tool" / "worktree_launcher.py"
    prepared = subprocess.run([sys.executable, str(launcher), "prepare", str(config)], cwd=ROOT, text=True, capture_output=True, timeout=20)
    assert prepared.returncode == 0, prepared.stderr or prepared.stdout
    for index in (1, 2, 3):
        assert (tmp_path / f"TestProject_{index}").is_dir()

    # Fewer tasks now: clean must still discover and remove old _2/_3 worktrees.
    task_yaml.write_text("- prompt: one\n  validator: ai\n", encoding="utf-8")
    cleaned = subprocess.run(
        [sys.executable, str(launcher), "clean", str(config), "--delete-branches", "--force"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert cleaned.returncode == 0, cleaned.stderr or cleaned.stdout
    for index in (1, 2, 3):
        assert not (tmp_path / f"TestProject_{index}").exists()

    # An unrelated directory at the managed path must fail fast, not be reused.
    wrong = tmp_path / "TestProject_1"
    wrong.mkdir()
    rejected = subprocess.run([sys.executable, str(launcher), "prepare", str(config)], cwd=ROOT, text=True, capture_output=True, timeout=20)
    assert rejected.returncode == 2
    assert "not the expected Git worktree" in rejected.stderr
