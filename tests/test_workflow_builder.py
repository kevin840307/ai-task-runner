from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from workflow_builder.run import _materialize_builder_workflow, _publish, parser
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


def test_canonical_builder_assets_live_in_external_folder_and_runner_shim_still_works():
    canonical = ROOT / "workflow_builder" / "workflow_builder.yaml"
    prompt = ROOT / "workflow_builder" / "prompt.md"
    shim = ROOT / "runner" / "workflow" / "system" / "workflow_builder.yaml"
    assert canonical.is_file()
    assert prompt.is_file()
    assert shim.is_file()
    assert not (ROOT / "runner" / "prompts" / "system" / "workflow_builder.md").exists()
    canonical_text = canonical.read_text(encoding="utf-8")
    shim_text = shim.read_text(encoding="utf-8").replace("\\", "/")
    assert "prompt: prompt.md" in canonical_text
    assert '"workflow_builder/validation.py"' in canonical_text
    assert "{runner_root}" not in canonical_text
    assert "{validator}" not in canonical_text
    assert "workflow_builder/prompt.md" in shim_text
    assert '"workflow_builder/validation.py"' in shim_text
    assert "{runner_root}" not in shim_text
    assert "{validator}" not in shim_text



def test_builder_materializes_fixed_validator_as_absolute_path(tmp_path: Path):
    runtime_workflow = _materialize_builder_workflow(tmp_path)
    data = yaml.safe_load(runtime_workflow.read_text(encoding="utf-8"))
    command = data["stages"]["validate_workflow"]["command"]
    assert Path(command[1]).resolve() == (ROOT / "workflow_builder" / "validation.py").resolve()
    assert command[1] != "workflow_builder/validation.py"
    assert Path(data["stages"]["build_workflow"]["prompt"]).resolve() == (ROOT / "workflow_builder" / "prompt.md").resolve()


def test_canonical_builder_workflow_dryrun_closes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tool" / "workflow_dryrun.py"), str(ROOT / "workflow_builder" / "workflow_builder.yaml"), "--matrix", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["closed"] is True


def test_publish_cli_validates_and_publishes_existing_draft(tmp_path: Path):
    project, workflow = _draft(tmp_path)
    output = tmp_path / "published" / "saved.workflow.yaml"
    prompt_dir = tmp_path / "published" / "prompts"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "workflow_builder" / "publish.py"),
            "--project-root", str(project),
            "--draft-workflow", str(workflow),
            "--draft-prompt-dir", str(workflow.parent / "prompts"),
            "--output-workflow", str(output),
            "--output-prompt-dir", str(prompt_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert output.is_file()
    assert (prompt_dir / "work.md").is_file()


def test_builder_runner_uses_fixed_validator_without_cli_validator_injection():
    source = (ROOT / "workflow_builder" / "run.py").read_text(encoding="utf-8")
    command_block = source[source.index("command = [", source.index("def build")):source.index("if args.backend", source.index("def build"))]
    assert '"--validator",' not in command_block
    assert '"--validator-arg=--draft-workflow"' in command_block
