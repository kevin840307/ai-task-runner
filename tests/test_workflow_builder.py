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


def draft(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    root = project / ".ai-task-runner" / "workflow-builder" / "r1" / "draft"
    prompts = root / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "work.md").write_text("Goal: {{ goal }}\n", encoding="utf-8")
    workflow = root / "workflow.yaml"
    workflow.write_text(
        "stages:\n"
        "  work:\n"
        "    type: base\n"
        "    prompt: prompts/work.md\n"
        "flow:\n"
        "  - work\n",
        encoding="utf-8",
    )
    return project, workflow, prompts


def test_builder_cli_has_one_output_workflow_path():
    args = parser().parse_args([
        "--project-root", "p",
        "--request", "build a workflow",
        "--output-workflow", "out.yaml",
    ])
    assert args.output_workflow == "out.yaml"
    assert not hasattr(args, "output_prompt_dir")


def test_builder_validator_reuses_real_dryrun(tmp_path):
    project, workflow, prompts = draft(tmp_path)
    payload = validate_draft(project, workflow, prompts)
    assert payload["ok"] is True
    assert payload["paths_total"] >= 1
    assert payload["paths_passed"] == payload["paths_total"]


def test_builder_validator_rejects_list_stages(tmp_path):
    project, workflow, prompts = draft(tmp_path)
    workflow.write_text(
        "stages:\n"
        "  - name: planning\n"
        "    type: plan\n"
        "flow:\n"
        "  - planning\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mapping/object keyed by Stage id"):
        validate_draft(project, workflow, prompts)


def test_builder_prompt_describes_only_current_graph_contract():
    text = (ROOT / "workflow_builder" / "prompt.md").read_text(encoding="utf-8")
    assert "One \u0060stages.<name>\u0060 entry is exactly one graph/UI node." in text
    assert "\u0060flow\u0060 is only the ordered list of unique Stage names." in text
    assert "routes.pass" in text
    assert "routes.fail" in text
    assert "routes.error" in text
    for removed in ("restart_at", "max_attempts", "on_exhausted", "per-Stage retry"):
        assert removed in text


def test_builder_runner_uses_shared_runner_reliability_only():
    run_source = (ROOT / "workflow_builder" / "run.py").read_text(encoding="utf-8")
    control = (ROOT / "workflow_builder" / "runner_control.py").read_text(encoding="utf-8")
    assert "--max-cycles" not in run_source
    assert "run_with_recovery" not in run_source
    assert "max_attempts" not in control
    assert "def run_runner" in control
    assert "cancel.request" in control


def test_publish_places_workflow_and_generated_prompts_in_one_flat_folder(tmp_path):
    _project, workflow, prompts = draft(tmp_path)
    output = tmp_path / "published" / "custom.workflow.yaml"

    result = _publish(workflow, prompts, output, overwrite=False)

    prompt = output.parent / "work.md"
    assert Path(result["workflow"]) == output.resolve()
    assert prompt.is_file()
    data = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert data["stages"]["work"]["prompt"] == "work.md"
    assert Path(result["prompts"][0]).parent == output.parent.resolve()


def test_publish_never_overwrites_without_flag(tmp_path):
    _project, workflow, prompts = draft(tmp_path)
    output = tmp_path / "published" / "custom.workflow.yaml"
    output.parent.mkdir(parents=True)
    output.write_text("existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        _publish(workflow, prompts, output, overwrite=False)

    assert output.read_text(encoding="utf-8") == "existing\n"


def test_builder_materializes_trusted_validator_and_prompt_as_absolute_paths(tmp_path):
    runtime_workflow = _materialize_builder_workflow(tmp_path)
    data = yaml.safe_load(runtime_workflow.read_text(encoding="utf-8"))
    command = data["stages"]["validate_workflow"]["command"]
    assert Path(command[1]).resolve() == (ROOT / "workflow_builder" / "validation.py").resolve()
    assert Path(data["stages"]["build_workflow"]["prompt"]).resolve() == (
        ROOT / "workflow_builder" / "prompt.md"
    ).resolve()


def test_builder_workflow_is_itself_a_result_edge_closed_loop():
    data = yaml.safe_load(
        (ROOT / "workflow_builder" / "workflow_builder.yaml").read_text(encoding="utf-8")
    )
    assert data["flow"] == ["build_workflow", "validate_workflow"]
    assert data["stages"]["validate_workflow"]["routes"] == {"fail": "build_workflow"}

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tool" / "workflow_dryrun.py"),
            str(ROOT / "workflow_builder" / "workflow_builder.yaml"),
            "--matrix",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["closed"] is True


def test_publish_cli_uses_same_flat_asset_contract(tmp_path):
    project, workflow, prompts = draft(tmp_path)
    output = tmp_path / "published" / "saved.workflow.yaml"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "workflow_builder" / "publish.py"),
            "--project-root", str(project),
            "--draft-workflow", str(workflow),
            "--draft-prompt-dir", str(prompts),
            "--output-workflow", str(output),
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
    assert (output.parent / "work.md").is_file()
