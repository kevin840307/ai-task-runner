from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from workflow_builder.run import _publish, parser
from workflow_builder.validation import validate_draft

ROOT = Path(__file__).resolve().parents[1]


def _draft(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    draft = project / ".ai-task-runner" / "workflow-builder" / "r1" / "draft"
    prompts = draft / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "work.md").write_text("Goal: {{ goal }}\n", encoding="utf-8")
    workflow = draft / "workflow.yaml"
    workflow.write_text(
        "stages:\n"
        "  work:\n"
        "    type: base\n"
        "    prompt: prompts/work.md\n"
        "flow:\n"
        "  - work\n",
        encoding="utf-8",
    )
    return project, workflow


def test_workflow_builder_cli_requires_project_request_and_output():
    args = parser().parse_args([
        "--project-root", "p",
        "--request", "build a workflow",
        "--output-workflow", "out.yaml",
    ])
    assert args.request == "build a workflow"
    assert args.output_workflow == "out.yaml"


def test_workflow_builder_validator_runs_matrix_dryrun(tmp_path: Path):
    project, workflow = _draft(tmp_path)
    payload = validate_draft(project, workflow, workflow.parent / "prompts")
    assert payload["ok"] is True
    assert payload["paths_total"] >= 1
    assert payload["paths_passed"] == payload["paths_total"]


def test_workflow_builder_validator_rejects_missing_prompt(tmp_path: Path):
    project, workflow = _draft(tmp_path)
    (workflow.parent / "prompts" / "work.md").unlink()
    with pytest.raises(ValueError, match="missing Prompt"):
        validate_draft(project, workflow, workflow.parent / "prompts")


def test_workflow_builder_publish_rewrites_generated_prompt_and_validates_final_path(tmp_path: Path):
    project, workflow = _draft(tmp_path)
    output = tmp_path / "published" / "custom.workflow.yaml"
    prompt_dir = tmp_path / "published" / "prompts"
    result = _publish(
        workflow,
        workflow.parent / "prompts",
        output,
        prompt_dir,
        overwrite=False,
    )
    assert Path(result["workflow"]) == output.resolve()
    assert (prompt_dir / "work.md").is_file()
    data = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert data["stages"]["work"]["prompt"] == "prompts/work.md"

    dryrun = subprocess.run(
        [sys.executable, str(ROOT / "tool" / "workflow_dryrun.py"), str(output), "--matrix", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert dryrun.returncode == 0, dryrun.stdout + dryrun.stderr
    assert json.loads(dryrun.stdout)["closed"] is True


def test_workflow_builder_publish_never_overwrites_without_flag(tmp_path: Path):
    _project, workflow = _draft(tmp_path)
    output = tmp_path / "published" / "custom.workflow.yaml"
    output.parent.mkdir(parents=True)
    output.write_text("existing\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="already exists"):
        _publish(workflow, workflow.parent / "prompts", output, output.parent / "prompts", overwrite=False)
    assert output.read_text(encoding="utf-8") == "existing\n"
