import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from runner.ui_projects import register_ui_project


def test_register_ui_project_adds_deduped_project_to_ui_list(tmp_path):
    repo = tmp_path / "repo"
    project_a = tmp_path / "alpha"
    project_b = tmp_path / "beta"
    project_a.mkdir()
    project_b.mkdir()
    data = repo / "ui" / "data"
    data.mkdir(parents=True)
    projects = data / "projects.json"
    projects.write_text(
        json.dumps([
            {"name": "Alpha old", "path": str(project_a)},
            {"name": "Beta", "path": str(project_b)},
        ]),
        encoding="utf-8",
    )

    register_ui_project(project_a, repo_root=repo)

    rows = json.loads(projects.read_text(encoding="utf-8"))
    assert rows == [
        {"name": "alpha", "path": str(project_a.resolve())},
        {"name": "Beta", "path": str(project_b)},
    ]


def test_register_ui_project_is_best_effort_for_missing_project(tmp_path):
    repo = tmp_path / "repo"

    register_ui_project(tmp_path / "missing", repo_root=repo)

    assert not (repo / "ui" / "data" / "projects.json").exists()


def test_register_ui_project_preserves_concurrent_cli_updates(tmp_path):
    repo = tmp_path / "repo"
    projects = [tmp_path / f"project-{index}" for index in range(20)]
    for project in projects:
        project.mkdir()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(
            lambda project: register_ui_project(project, repo_root=repo),
            projects,
        ))

    rows = json.loads(
        (repo / "ui" / "data" / "projects.json").read_text(encoding="utf-8")
    )
    paths = {row["path"] for row in rows}

    assert paths == {str(project.resolve()) for project in projects}
    assert not (repo / "ui" / "data" / "projects.json.lock").exists()
