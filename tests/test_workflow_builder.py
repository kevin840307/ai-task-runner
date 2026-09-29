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


def test_builder_cli_publishes_to_one_asset_package():
    args = parser().parse_args([
        "--project-root", "p",
        "--request", "build a workflow",
        "--output-asset-root", "assets",
        "--workflow-name", "demo.workflow.yaml",
    ])
    assert args.output_asset_root == "assets"
    assert args.workflow_name == "demo.workflow.yaml"
    assert not hasattr(args, "output_workflow")
    assert not hasattr(args, "output_prompt_dir")


def test_builder_validator_reuses_real_dryrun(tmp_path):
    project, workflow, prompts = draft(tmp_path)
    payload = validate_draft(project, workflow, prompts)
    assert payload["ok"] is True
    assert payload["paths_passed"] == payload["paths_total"]


def test_builder_validator_rejects_prompt_outside_draft_prompt_dir(tmp_path):
    project, workflow, prompts = draft(tmp_path)
    outside = workflow.parent / "outside.md"
    outside.write_text("{{ goal }}", encoding="utf-8")
    workflow.write_text(
        "stages:\n"
        "  work:\n"
        "    type: base\n"
        "    prompt: outside.md\n"
        "flow: [work]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Draft Prompt directory"):
        validate_draft(project, workflow, prompts)


def test_builder_prompt_describes_current_graph_and_prompt_contract():
    text = (ROOT / "workflow_builder" / "prompt.md").read_text(encoding="utf-8")
    assert "One `stages.<name>` entry is exactly one graph/UI node." in text
    assert "`flow` is only the ordered list of unique Stage names." in text
    assert "prompts/<filename>.md" in text
    assert "assets/prompts/workflow/<workflow-name>/" in text
    assert "common/review.md" in text
    for removed in ("restart_at", "max_attempts", "on_exhausted", "per-Stage retry"):
        assert removed in text


def test_builder_runner_has_no_second_retry_runtime():
    run_source = (ROOT / "workflow_builder" / "run.py").read_text(encoding="utf-8")
    control = (ROOT / "workflow_builder" / "runner_control.py").read_text(encoding="utf-8")
    assert "--max-cycles" not in run_source
    assert "run_with_recovery" not in run_source
    assert "max_attempts" not in control
    assert "def run_runner" in control


def test_publish_separates_workflow_and_workflow_owned_prompts(tmp_path):
    _project, workflow, prompts = draft(tmp_path)
    assets = tmp_path / "assets"

    result = _publish(
        workflow,
        prompts,
        assets,
        "demo.workflow.yaml",
        overwrite=False,
    )

    output = assets / "workflows" / "demo.workflow.yaml"
    prompt = assets / "prompts" / "workflow" / "demo" / "work.md"
    assert Path(result["workflow"]) == output.resolve()
    assert prompt.is_file()
    data = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert data["stages"]["work"]["prompt"] == "workflow/demo/work.md"
    assert [Path(path) for path in result["prompts"]] == [prompt.resolve()]


def test_publish_never_overwrites_without_flag(tmp_path):
    _project, workflow, prompts = draft(tmp_path)
    assets = tmp_path / "assets"
    output = assets / "workflows" / "demo.workflow.yaml"
    output.parent.mkdir(parents=True)
    output.write_text("existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        _publish(workflow, prompts, assets, "demo.workflow.yaml", overwrite=False)

    assert output.read_text(encoding="utf-8") == "existing\n"


def test_builder_internal_workflow_is_a_result_edge_closed_loop(tmp_path):
    runtime_workflow = _materialize_builder_workflow(tmp_path)
    data = yaml.safe_load(runtime_workflow.read_text(encoding="utf-8"))
    assert data["flow"] == ["build_workflow", "validate_workflow"]
    assert data["stages"]["validate_workflow"]["routes"] == {"fail": "build_workflow"}
    assert Path(data["stages"]["validate_workflow"]["command"][1]).resolve() == (
        ROOT / "workflow_builder" / "validation.py"
    ).resolve()
    assert Path(data["stages"]["build_workflow"]["prompt"]).resolve() == (
        ROOT / "workflow_builder" / "prompt.md"
    ).resolve()


def test_publish_cli_uses_same_asset_package_contract(tmp_path):
    project, workflow, prompts = draft(tmp_path)
    assets = tmp_path / "published-assets"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "workflow_builder" / "publish.py"),
            "--project-root", str(project),
            "--draft-workflow", str(workflow),
            "--draft-prompt-dir", str(prompts),
            "--output-asset-root", str(assets),
            "--workflow-name", "saved.workflow.yaml",
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
    assert (assets / "workflows" / "saved.workflow.yaml").is_file()
    assert (assets / "prompts" / "workflow" / "saved" / "work.md").is_file()
