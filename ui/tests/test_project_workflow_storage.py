from __future__ import annotations

from pathlib import Path

from ui.server import UIState


def _state(tmp_path: Path) -> tuple[UIState, Path]:
    for rel in (
        "runner/workflow/system", "runner/workflow/custom", "runner/prompts/stages",
        "runner/prompts/system", "runner/prompts/custom", "runner/config", "runner/backends",
        "ui/data", "tool",
    ):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    (tmp_path / "runner/prompts/context.py").write_text(
        "def build_stage_prompt_context(ctx, stage, previous=None): return {'goal':'','project':{'root':''}}\n",
        encoding="utf-8",
    )
    (tmp_path / "runner/prompts/loader.py").write_text("def render_prompt(name, values=None): return ''\n", encoding="utf-8")
    (tmp_path / "runner/config/defaults.py").write_text("DEFAULT_BACKEND='qwen'\n", encoding="utf-8")
    (tmp_path / "runner/backends/qwen.py").write_text("class QwenBackend: name='qwen'\n", encoding="utf-8")
    (tmp_path / "tool/workflow_dryrun.py").write_text(
        "import json; print(json.dumps({'closed': True, 'valid': True, 'paths_passed': 1, 'paths_total': 1}))\n",
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    return UIState(tmp_path), project


def test_project_policy_yaml_is_not_discovered_as_workflow(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    (project / ".ai-task-runner.yaml").write_text("backend: qwen\n", encoding="utf-8")
    assert not [row for row in state.studio_files(project)["workflows"] if row["scope"] == "project"]


def test_project_workflow_and_prompt_use_owned_package(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    created = state.studio_workflow_create("regression", "project", project)
    workflow = Path(created["item"]["path"])
    assert workflow.relative_to(project).as_posix() == ".ai-task-runner/workflows/regression/workflow/regression.workflow.yaml"
    assert state.studio_files(project)["project_folders"] == ["regression"]

    prompt = state.studio_prompt_create("review", "project", project, "regression")
    prompt_path = Path(prompt["item"]["path"])
    assert prompt_path.relative_to(project).as_posix() == ".ai-task-runner/workflows/regression/prompts/review.md"
    state._resolve_studio_file(prompt["item"]["id"], project)


def test_generator_project_output_matches_owned_package(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    _raw, folder, destination, workflow, prompts = state._workflow_output_paths(project, "e2e", "main.workflow.yaml", "project")
    assert folder == "e2e" and destination == "project"
    assert workflow.relative_to(project).as_posix() == ".ai-task-runner/workflows/e2e/workflow/main.workflow.yaml"
    assert prompts.relative_to(project).as_posix() == ".ai-task-runner/workflows/e2e/prompts"


def test_nested_support_workflow_dir_is_not_a_second_project_package(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    package = project / ".ai-task-runner/workflows/regression"
    (package / "workflow").mkdir(parents=True)
    (package / "workflow/main.workflow.yaml").write_text("stages: {planning: {type: plan}}\nflow: [planning]\n", encoding="utf-8")
    (package / "assets/workflow").mkdir(parents=True)
    (package / "assets/workflow/not-a-workflow.yaml").write_text("asset: true\n", encoding="utf-8")
    rows = [row for row in state.studio_files(project)["workflows"] if row["scope"] == "project"]
    assert [Path(row["path"]).name for row in rows] == ["main.workflow.yaml"]
    assert state.studio_files(project)["project_folders"] == ["regression"]


def test_project_workflow_folder_rejects_nested_and_absolute_paths(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    for bad in ("a/b", "/absolute", "C:/absolute", "../escape"):
        import pytest
        with pytest.raises(ValueError):
            state._workflow_output_paths(project, bad, "main.workflow.yaml", "project")
