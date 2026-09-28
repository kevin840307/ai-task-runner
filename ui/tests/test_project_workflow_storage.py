from __future__ import annotations

from pathlib import Path

from ui.server import UIState


def _state(tmp_path: Path) -> tuple[UIState, Path]:
    for rel in (
        "runner/workflows",
        "runner/prompts",
        "runner/config",
        "runner/backends",
        "ui/data",
        "tool",
    ):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    (tmp_path / "runner/workflows/execution.md").write_text("{{ goal }}\n", encoding="utf-8")
    (tmp_path / "runner/prompts/context.py").write_text(
        "def build_stage_prompt_context(ctx, stage, previous=None): return {'goal':'','project':{'root':''}}\n",
        encoding="utf-8",
    )
    (tmp_path / "runner/prompts/loader.py").write_text(
        "def render_prompt(name, values=None): return ''\n", encoding="utf-8"
    )
    (tmp_path / "runner/config/defaults.py").write_text("DEFAULT_BACKEND='qwen'\n", encoding="utf-8")
    (tmp_path / "runner/backends/qwen.py").write_text("class QwenBackend: name='qwen'\n", encoding="utf-8")
    (tmp_path / "tool/workflow_dryrun.py").write_text(
        "import json; print(json.dumps({'closed': True, 'valid': True}))\n",
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    return UIState(tmp_path), project


def test_project_policy_yaml_is_not_discovered_as_workflow(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    (project / ".ai-task-runner.yaml").write_text("backend: qwen\n", encoding="utf-8")
    assert not [row for row in state.studio_files(project)["workflows"] if row["scope"] == "project"]


def test_project_workflow_and_prompt_share_one_flat_editable_root(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    created = state.studio_workflow_create("regression", "project", project)
    workflow = Path(created["item"]["path"])
    assert workflow.relative_to(project).as_posix() == ".ai-task-runner/workflows/regression.workflow.yaml"

    prompt = state.studio_prompt_create("review", "project", project)
    prompt_path = Path(prompt["item"]["path"])
    assert prompt_path.relative_to(project).as_posix() == ".ai-task-runner/workflows/review.md"

    rows = state.studio_files(project)
    assert [Path(row["path"]).name for row in rows["workflows"] if row["scope"] == "project"] == ["regression.workflow.yaml"]
    assert [Path(row["path"]).name for row in rows["prompts"] if row["scope"] == "project"] == ["review.md"]
    assert created["item"]["readonly"] is False
    assert prompt["item"]["readonly"] is False


def test_generator_project_output_uses_same_flat_root(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    raw, folder, scope, workflow, prompts = state._workflow_output_paths(
        project, "ignored", "main.workflow.yaml", "project"
    )
    assert raw == "main.workflow.yaml"
    assert folder == ""
    assert scope == "project"
    assert workflow.relative_to(project).as_posix() == ".ai-task-runner/workflows/main.workflow.yaml"
    assert prompts.relative_to(project).as_posix() == ".ai-task-runner/workflows"


def test_global_and_project_assets_use_same_file_shape(tmp_path: Path) -> None:
    state, project = _state(tmp_path)
    global_asset = state.studio_workflow_create("global_job", "global", project)
    project_asset = state.studio_workflow_create("project_job", "project", project)

    assert Path(global_asset["item"]["path"]).parent.name == "workflows"
    assert Path(project_asset["item"]["path"]).parent.name == "workflows"
    assert global_asset["item"]["group"] == "Global"
    assert project_asset["item"]["group"] == "Project"
