from __future__ import annotations

from pathlib import Path

from ui.server import UIState


def _state(tmp_path: Path) -> tuple[UIState, Path]:
    for rel in (
        "runner/assets/workflows",
        "runner/assets/prompts/common",
        "runner/config",
        "runner/agent",
        "ui/data",
        "tool",
    ):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    (tmp_path / "runner/assets/prompts/common/execution.md").write_text(
        "{{ goal }}\n", encoding="utf-8"
    )
    (tmp_path / "runner/config/defaults.py").write_text(
        "DEFAULT_BACKEND='qwen'\n", encoding="utf-8"
    )
    (tmp_path / "runner/agent/qwen.py").write_text(
        "class QwenBackend: name='qwen'\n", encoding="utf-8"
    )
    (tmp_path / "tool/workflow_dryrun.py").write_text(
        "import json; print(json.dumps({'closed': True, 'valid': True}))\n",
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    return UIState(tmp_path), project


def test_project_policy_yaml_is_not_discovered_as_workflow(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    (project / ".ai-task-runner.yaml").write_text(
        "backend: qwen\n", encoding="utf-8"
    )
    assert not [
        row
        for row in state.studio_files(project)["workflows"]
        if row["scope"] == "project"
    ]


def test_project_workflow_and_categorized_prompt_use_split_asset_roots(
    tmp_path: Path,
) -> None:
    state, project = _state(tmp_path)
    workflow = state.studio_workflow_create("regression", "project", project)
    prompt = state.studio_prompt_create("common/review", "project", project)

    workflow_path = Path(workflow["item"]["path"])
    prompt_path = Path(prompt["item"]["path"])
    assert workflow_path.relative_to(project).as_posix() == (
        ".ai-task-runner/assets/workflows/regression.workflow.yaml"
    )
    assert prompt_path.relative_to(project).as_posix() == (
        ".ai-task-runner/assets/prompts/common/review.md"
    )
    assert prompt["item"]["reference"] == "common/review.md"

    rows = state.studio_files(project)
    assert [
        Path(row["path"]).name
        for row in rows["workflows"]
        if row["scope"] == "project"
    ] == ["regression.workflow.yaml"]
    assert [
        row["reference"]
        for row in rows["prompts"]
        if row["scope"] == "project"
    ] == ["common/review.md"]
    assert workflow["item"]["readonly"] is False
    assert prompt["item"]["readonly"] is False


def test_generator_project_workflow_output_uses_workflow_asset_root(
    tmp_path: Path,
) -> None:
    state, project = _state(tmp_path)
    raw, folder, scope, workflow, asset_root = state._workflow_output_paths(
        project, "ignored", "main.workflow.yaml", "project"
    )
    assert raw == "main.workflow.yaml"
    assert folder == ""
    assert scope == "project"
    assert workflow.relative_to(project).as_posix() == (
        ".ai-task-runner/assets/workflows/main.workflow.yaml"
    )
    assert asset_root.relative_to(project).as_posix() == (
        ".ai-task-runner/assets/workflows"
    )


def test_global_and_project_assets_are_structurally_symmetric(
    tmp_path: Path,
) -> None:
    state, project = _state(tmp_path)
    global_workflow = state.studio_workflow_create("global_job", "global", project)
    global_prompt = state.studio_prompt_create("common/global_review", "global", project)
    project_workflow = state.studio_workflow_create("project_job", "project", project)
    project_prompt = state.studio_prompt_create("common/project_review", "project", project)

    assert Path(global_workflow["item"]["path"]).parent == (
        tmp_path / "runner/assets/workflows"
    ).resolve()
    assert Path(global_prompt["item"]["path"]).parent == (
        tmp_path / "runner/assets/prompts/common"
    ).resolve()
    assert Path(project_workflow["item"]["path"]).parent == (
        project / ".ai-task-runner/assets/workflows"
    ).resolve()
    assert Path(project_prompt["item"]["path"]).parent == (
        project / ".ai-task-runner/assets/prompts/common"
    ).resolve()
