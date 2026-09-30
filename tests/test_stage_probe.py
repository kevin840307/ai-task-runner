"""Single-Stage probes stop before the next Workflow node."""

from argparse import Namespace
from pathlib import Path

import yaml

from runner.workflow.stages import StageResult
from tool.stage_probe import _draft_next, run_probe


def test_stage_probe_reports_input_output_and_next_without_running_next(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    workflow = tmp_path / "workflow.yaml"
    marker = project / "next-ran.txt"
    workflow.write_text(
        yaml.safe_dump({
            "stages": {
                "first": {
                    "type": "command",
                    "command": [
                        "{python}", "-c",
                        "import json,sys; print(json.load(open(sys.argv[1]))['goal'])",
                        "{state_file}",
                    ],
                },
                "second": {
                    "type": "command",
                    "command": ["{python}", "-c", "from pathlib import Path; Path('next-ran.txt').write_text('ran')"],
                },
            },
            "flow": ["first", "second"],
        }),
        encoding="utf-8",
    )

    result = run_probe(Namespace(
        project_root=str(project), workflow=str(workflow), stage="first",
        input="one stage input", backend="", keep_work=False,
    ))

    assert result["status"] == "pass"
    assert result["output"].strip() == "one stage input"
    assert result["next"] == "second"
    assert not marker.exists()
    assert not Path(result["work_dir"]).exists()


def test_stage_probe_accepts_disconnected_stage(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        yaml.safe_dump({
            "stages": {
                "first": {"type": "command", "command": ["{python}", "-c", "print('first')"]},
                "detached": {"type": "command", "command": ["{python}", "-c", "print('detached')"]},
            },
            "flow": ["first"],
        }),
        encoding="utf-8",
    )

    result = run_probe(Namespace(
        project_root=str(project), workflow=str(workflow), stage="detached",
        input="", backend="", keep_work=False,
    ))

    assert result["output"].strip() == "detached"
    assert result["next"] == "done"


def test_stage_probe_reports_dynamic_handoff_target_without_running_it():
    draft = {
        "stages": {
            "router": {"type": "handoff", "targets": ["worker", "final_validate"]},
            "worker": {"type": "base"},
            "final_validate": {"type": "ai_validator", "validator": "ai"},
        },
        "flow": ["router", "worker", "final_validate"],
    }
    result = StageResult(
        "router",
        "pass",
        data={"target": "final_validate", "reason": "ready"},
        kind="handoff",
    )

    assert _draft_next(draft, "router", result) == ("final_validate", "handoff")


