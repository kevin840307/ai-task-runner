from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from runner.config.runtime import RuntimeConfig
from runner.runtime.run_state import RunState
from runner.workflow.registry import create_stage, stage_catalog
from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec
from runner.workflow.stages import StageContext, StageResult
from runner.workflow.stage_executor import StageAction


def context(tmp_path: Path) -> StageContext:
    state = RunState("run", "goal", str(tmp_path))
    ai = SimpleNamespace(session_id="S1")
    work = tmp_path / ".work"
    work.mkdir(exist_ok=True)
    return StageContext(
        config=RuntimeConfig(
            stage_retries=0,
            retry_delay=0,
            retry_max_delay=0,
        ),
        root=tmp_path,
        work=work,
        state=state,
        ai_client=ai,
        state_file=tmp_path / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda stage, detail="": setattr(state, "stage", stage),
    )


def test_base_stage_exposes_track_changes_capability():
    stage = BaseStage(BaseStageSpec(name="inspect", status="inspect", track_changes=True))
    assert stage.track_changes is True
    action = StageAction(stage, SimpleNamespace(root=Path("."), work=Path(".")))
    assert action.track_changes is True


def test_command_stage_catalog_has_behavior_fields_not_retry_policy():
    options = {item["name"] for item in stage_catalog()["command"]["options"]}
    assert {
        "track_changes",
        "tolerate_restored_changes",
        "result_kind",
        "clean_work",
        "timeout",
        "cwd",
        "command",
    } <= options
    assert "retry" not in options
    assert "skip_on_error" not in options


def test_command_stage_receives_execution_behavior_only():
    stage = create_stage({
        "type": "command",
        "name": "script",
        "status": "script",
        "command": ["{python}", "tool.py"],
        "track_changes": True,
        "tolerate_restored_changes": True,
    })
    assert stage.track_changes is True
    assert stage.tolerate_restored_changes is True
    assert not hasattr(stage, "retry")
    assert not hasattr(stage, "skip_on_error")


def test_validation_command_uses_shared_process_boundary(monkeypatch, tmp_path):
    from runner.workflow.stages import command as module

    validator = tmp_path / "validate.py"
    validator.write_text("print('ok')", encoding="utf-8")
    ctx = context(tmp_path)
    ctx.validator_path = validator
    ctx.config.validator_args = []
    ctx.config.validator_timeout = 10
    seen = {}

    def fake(ctx, stage, command, timeout, label, **kwargs):
        seen["command"] = command
        seen["timeout"] = timeout
        return StageResult(stage, "pass", output="VALID")

    monkeypatch.setattr(module, "run_stage_process", fake)
    stage = create_stage({
        "type": "command",
        "name": "validate",
        "status": "validate",
        "result_kind": "validation",
        "command": ["{python}", "{validator}", "{validator_args}"],
    })
    result = stage.run(ctx)
    assert result.status == "pass"
    assert result.output == "VALID"
    assert seen["command"][1] == str(validator)
    assert seen["timeout"] == 10


def test_command_stage_uses_shared_process_boundary(monkeypatch, tmp_path):
    from runner.workflow.stages import command as module

    ctx = context(tmp_path)
    ctx.config.agent_timeout = 10
    seen = {}

    def fake(ctx, stage, command, timeout, label, **kwargs):
        seen["command"] = command
        return StageResult(stage, "pass", output="COMMAND_OK")

    monkeypatch.setattr(module, "run_stage_process", fake)
    stage = create_stage({
        "type": "command",
        "name": "check",
        "status": "check",
        "command": ["tool", "--check"],
    })
    result = stage.run(ctx)
    assert result.status == "pass"
    assert result.output == "COMMAND_OK"
    assert seen["command"] == ["tool", "--check"]


def test_orchestration_stage_catalog_reuses_stage_executor_contract():
    catalog = stage_catalog()
    assert "handoff" in catalog
    assert "discussion_controller" not in catalog
    assert "discussion" not in catalog
    handoff_options = {item["name"] for item in catalog["handoff"]["options"]}
    base_options = {item["name"]: item for item in catalog["base"]["options"]}
    assert "targets" in handoff_options
    assert base_options["session_policy"]["values"] == ["auto", "main", "role", "fresh"]
    assert "fresh_session_each_run" not in base_options
    assert "fresh_session_on_start" not in base_options
    for stage_type, entry in catalog.items():
        option_names = {item["name"] for item in entry["options"]}
        assert "fresh_session_each_run" not in option_names, stage_type
        assert "fresh_session_on_start" not in option_names, stage_type
