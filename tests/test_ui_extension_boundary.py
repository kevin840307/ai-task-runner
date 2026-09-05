from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.errors import RunnerError
from runner.extensions import discover_extensions
from runner.prompts.loader import save_prompt
from runner.resources import read_text
from runner.workflow.loader import load_workflow, save_workflow
from runner.workflow.registry import STAGE_REGISTRY, register_stage, stage_catalog, workflow_catalog
from runner.workflow.snapshot import freeze_workflow, load_snapshot


def _workflow_text(prompt: str = "") -> str:
    prompt_line = f"    prompt: {prompt}\n" if prompt else ""
    return (
        "stages:\n"
        "  execute:\n"
        "    status: Execute\n"
        f"{prompt_line}"
        "  validate_file:\n"
        "    type: command\n"
        "    status: Validate\n"
        "    result_kind: validation\n"
        "    command: \"{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}\"\n"
        "flow: [execute, validate_file]\n"
    )


def test_stage_catalog_uses_registered_spec_as_single_schema_source():
    catalog = stage_catalog()
    assert {"base", "command", "plan"} <= set(catalog)
    command_fields = {item["name"] for item in catalog["command"]["options"]}
    assert {"status", "command", "cwd", "result_kind", "clean_work", "retry"} <= command_fields
    assert "name" not in command_fields
    contract = workflow_catalog()
    assert "command" in contract["stage_types"]
    assert set(contract["stage_types"]) == {"ai_validator", "base", "command", "plan", "review", "task"}
    assert contract["flow_options"]["scope"]["values"] == ["task"]


def test_workflow_save_validates_then_atomically_replaces(tmp_path):
    path = tmp_path / "workflow.yaml"
    first_hash = save_workflow(path, _workflow_text())
    text, current_hash = read_text(path)
    assert current_hash == first_hash
    assert load_workflow(path)

    with pytest.raises(RunnerError):
        save_workflow(path, "stages: []\nflow: []\n", expected_hash=current_hash)
    assert read_text(path)[0] == text


def test_resource_hash_prevents_silent_overwrite(tmp_path):
    path = tmp_path / "workflow.yaml"
    expected = save_workflow(path, _workflow_text())
    path.write_text(_workflow_text().replace("Execute", "Changed"), encoding="utf-8")
    with pytest.raises(RunnerError, match="changed since it was read"):
        save_workflow(path, _workflow_text(), expected_hash=expected)


def test_prompt_save_rejects_invalid_jinja_without_touching_file(tmp_path):
    path = tmp_path / "prompt.md"
    old_hash = save_prompt(path, "Hello {{ task }}")
    with pytest.raises(RunnerError, match="invalid prompt template"):
        save_prompt(path, "Hello {{", expected_hash=old_hash)
    assert path.read_text(encoding="utf-8") == "Hello {{ task }}"


def test_workflow_snapshot_freezes_local_prompt_content(tmp_path):
    prompt = tmp_path / "execute.md"
    prompt.write_text("version A", encoding="utf-8")
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(_workflow_text("execute.md"), encoding="utf-8")
    workflow = load_workflow(workflow_file)

    frozen = freeze_workflow(workflow, tmp_path, ".run")
    prompt.write_text("version B", encoding="utf-8")
    loaded = load_snapshot(tmp_path, ".run")

    assert loaded == frozen
    frozen_prompt = Path(frozen[0]["prompt"])
    assert frozen_prompt.read_text(encoding="utf-8") == "version A"


def test_command_stage_runs_python_out_of_process(tmp_path):
    from runner.config.runtime import RuntimeConfig
    from runner.runtime.run_state import RunState
    from runner.workflow.registry import create_stage
    from runner.workflow.stages.contracts import StageContext

    script = tmp_path / "stage.py"
    script.write_text("from pathlib import Path\nPath('marker.txt').write_text('ok', encoding='utf-8')\n", encoding="utf-8")
    work = tmp_path / ".work"
    work.mkdir()
    ctx = StageContext(
        config=RuntimeConfig(agent_timeout=10), root=tmp_path, work=work,
        state=RunState("run", "goal", str(tmp_path)), ai_client=SimpleNamespace(session_id=""),
        state_file=tmp_path / "state.json", validator_path=None, validator_is_ai=False,
        save_state=lambda: None, set_stage=lambda *_: None,
    )
    stage = create_stage({"type":"command","name":"script","status":"Run","command":["{python}","stage.py"]})
    result = stage.run(ctx)
    assert result.status == "pass"
    assert (tmp_path / "marker.txt").read_text(encoding="utf-8") == "ok"


def test_extension_registration_happens_before_catalog_validation(monkeypatch):
    import runner.extensions as extension_module

    @dataclass(frozen=True)
    class Spec:
        name: str
        status: str

    class CustomStage:
        spec_class = Spec

        def __init__(self, spec):
            self.spec = spec
            self.name = spec.name

    class Point:
        name = "test"

        @staticmethod
        def load():
            return lambda: register_stage("external_test", CustomStage)

    class Points(list):
        def select(self, *, group):
            return self if group == extension_module.EXTENSION_GROUP else []

    extension_module.discover_extensions.cache_clear()
    monkeypatch.setattr(extension_module, "entry_points", lambda: Points([Point()]))
    try:
        assert discover_extensions() == ("test",)
        assert "external_test" in stage_catalog()
    finally:
        STAGE_REGISTRY.pop("external_test", None)
        extension_module.discover_extensions.cache_clear()


def test_yaml_child_resume_uses_snapshot_before_changed_workflow_source(tmp_path):
    from runner.config.runtime import RuntimeConfig
    from runner.script_loader import load_yaml_script
    from runner.script_runner import build_script_item_config

    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(_workflow_text(), encoding="utf-8")
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: build\n  validator: validator.py\n  workflow_file: workflow.yaml\n",
        encoding="utf-8",
    )
    args = RuntimeConfig(
        project_root=str(tmp_path),
        script=str(script),
        goal="",
        validator=None,
        work_dir=".ai-task-runner",
    )
    first = build_script_item_config(args, load_yaml_script(script)[0], 1)
    frozen = freeze_workflow(first.workflow, first.project_root, first.work_dir)
    state = Path(first.project_root, first.work_dir, "state.json")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{}", encoding="utf-8")

    workflow_file.write_text("invalid: [", encoding="utf-8")
    args.resume = True
    resumed = build_script_item_config(args, load_yaml_script(script)[0], 1)

    assert resumed.resume is True
    assert resumed.workflow == frozen


def test_ui_editor_uses_owner_modules_without_exposure_facade():
    from runner.prompts.loader import save_prompt
    from runner.resources import delete, read_text
    from runner.workflow.loader import save_workflow
    from runner.workflow.registry import stage_catalog

    assert not Path("runner/tooling.py").exists()
    assert all(callable(fn) for fn in (read_text, delete, save_prompt, save_workflow, stage_catalog))


def test_resume_prefers_frozen_goal_and_ai_validator_prompt_when_sources_are_gone(tmp_path):
    from runner.api import RunRequest
    from runner.workflow.snapshot import freeze_run_resource

    goal = tmp_path / "goal.md"
    ai_prompt = tmp_path / "ai-validation.md"
    goal.write_text("goal version A", encoding="utf-8")
    ai_prompt.write_text("validator version A", encoding="utf-8")
    freeze_run_resource(goal, tmp_path, ".run", "goal")
    freeze_run_resource(ai_prompt, tmp_path, ".run", "ai_validator_prompt")
    goal.unlink()
    ai_prompt.unlink()

    config = RunRequest(
        goal_file=str(goal),
        ai_validator_prompt_file=str(ai_prompt),
        validator="ai",
        project_root=str(tmp_path),
        work_dir=".run",
        resume=True,
    ).normalized_config()

    assert config.goal == "goal version A"
    assert config.ai_validator_prompt == "validator version A"
    assert Path(config.goal_file).read_text(encoding="utf-8") == "goal version A"
    assert Path(config.ai_validator_prompt_file).read_text(encoding="utf-8") == "validator version A"


def test_yaml_child_resume_uses_frozen_files_after_source_deletion(tmp_path):
    from runner.config.runtime import RuntimeConfig
    from runner.script_loader import load_yaml_script
    from runner.script_runner import build_script_item_config
    from runner.workflow.snapshot import freeze_run_resource

    goal = tmp_path / "goal.md"
    ai_prompt = tmp_path / "ai-validation.md"
    goal.write_text("child goal A", encoding="utf-8")
    ai_prompt.write_text("child validator A", encoding="utf-8")
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- goal_file: goal.md\n"
        "  validator: ai\n"
        "  ai_validator_prompt_file: ai-validation.md\n",
        encoding="utf-8",
    )
    args = RuntimeConfig(
        project_root=str(tmp_path),
        script=str(script),
        goal="",
        validator=None,
        work_dir=".ai-task-runner",
    )
    first_item = load_yaml_script(script)[0]
    first = build_script_item_config(args, first_item, 1)
    freeze_run_resource(first.goal_file, first.project_root, first.work_dir, "goal")
    freeze_run_resource(
        first.ai_validator_prompt_file,
        first.project_root,
        first.work_dir,
        "ai_validator_prompt",
    )
    state = Path(first.project_root, first.work_dir, "state.json")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{}", encoding="utf-8")
    goal.unlink()
    ai_prompt.unlink()

    args.resume = True
    resumed_item = load_yaml_script(script, allow_missing_files=True)[0]
    resumed = build_script_item_config(args, resumed_item, 1)

    assert resumed.goal == "child goal A"
    assert resumed.ai_validator_prompt == "child validator A"
    assert Path(resumed.goal_file).is_file()
    assert Path(resumed.ai_validator_prompt_file).is_file()


def test_workflow_catalog_tool_is_json_process_boundary():
    import json
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "tool/workflow_catalog.py"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload["stage_types"]) == {"ai_validator", "base", "command", "plan", "review", "task"}
    assert "command" in payload["stage_types"]
    assert payload["flow_options"]["scope"]["values"] == ["task"]
    assert payload["flow_options"]["repeat"]["minimum"] == 1
