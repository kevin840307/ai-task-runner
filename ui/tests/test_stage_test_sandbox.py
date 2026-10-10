"""Stage probe integration with an unsaved draft and disposable Project."""
from pathlib import Path
from tempfile import TemporaryDirectory

from ui.server import UIState


ROOT = Path(__file__).resolve().parents[2]


def test_unsaved_stage_draft_runs_once_without_touching_source_project():
    with TemporaryDirectory(prefix="stage-test-source-") as source_dir:
        source = Path(source_dir)
        workflow = source / ".ai-task-runner" / "assets" / "workflows" / "sample.yaml"
        workflow.parent.mkdir(parents=True)
        original = (
            "stages:\n"
            "  check:\n"
            "    type: command\n"
            "    command: ['{python}', '-c', \"print('SAVED')\"]\n"
            "  after:\n"
            "    type: command\n"
            "    command: ['{python}', '-c', \"print('AFTER')\"]\n"
            "flow: [check, after]\n"
        )
        workflow.write_text(original, encoding="utf-8")
        state = UIState(ROOT)
        file_id = state._encode_file_id(workflow, "workflow", "project")
        graph = {
            "stages": [
                {
                    "name": "check", "type": "command", "prompt": "",
                    "command": ["{python}", "-c", "from pathlib import Path; Path('marker.txt').write_text('test'); print('DRAFT')"],
                },
                {"name": "after", "type": "command", "command": ""},
            ],
            "flow": ["check", "after"],
            "routes": {},
        }

        result = state.studio_stage_test(file_id, "check", "input", source, graph=graph)

        assert result["status"] == "pass"
        assert "DRAFT" in result["output"]
        assert result["next"] == "after"
        assert workflow.read_text(encoding="utf-8") == original
        assert not (source / "marker.txt").exists()
        assert not Path(result["work_dir"]).parents[2].exists()
