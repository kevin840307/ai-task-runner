from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from runner.config.runtime import RuntimeConfig
from runner.errors import RunnerError
from runner.runtime.run_state import RunState
from runner.workflow.registry import create_stage, stage_catalog
from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec
from runner.workflow.stages.contracts import StageContext, StageResult
from runner.workflow.stages.executor import StageAction, StageExecutor


class Hooks:
    def before(self, action): return []
    def after(self, action, tokens): return []
    def change_detector(self, action, tokens, fallback): return fallback()


class ErrorStage:
    name = "custom"
    mode = "readonly"
    actor = "test"
    status = "custom"
    detail = ""
    run_state = "testing"
    retry = 0
    skip_on_error = False
    track_changes = False
    tolerate_restored_changes = False

    def __init__(self): self.calls = 0
    def run(self, ctx, previous=None): self.calls += 1; raise RunnerError("boom")
    def finish(self, ctx, result): return result


def context(tmp_path: Path) -> StageContext:
    state = RunState("run", "goal", str(tmp_path))
    ai = SimpleNamespace(session_id="S1")
    work = tmp_path / ".work"
    work.mkdir(exist_ok=True)
    return StageContext(
        config=RuntimeConfig(same_session_retries=2, stage_retry_delay=0),
        root=tmp_path, work=work, state=state, ai_client=ai,
        state_file=tmp_path / "state.json", validator_path=None,
        validator_is_ai=False, save_state=lambda: None,
        set_stage=lambda stage, detail="": setattr(state, "stage", stage),
    )


def test_base_stage_exposes_track_changes_capability():
    stage = BaseStage(BaseStageSpec(name="inspect", status="inspect", track_changes=True))
    assert stage.track_changes is True
    assert StageAction(stage, SimpleNamespace(root=Path('.'), work=Path('.'))).track_changes is True


def test_command_stage_exposes_common_execution_capabilities():
    options = {item["name"] for item in stage_catalog()["command"]["options"]}
    assert {"retry", "skip_on_error", "track_changes", "tolerate_restored_changes", "result_kind", "clean_work"} <= options


def test_command_stage_receives_common_execution_capabilities():
    stage = create_stage({
        "type": "command", "name": "script", "status": "script",
        "command": ["{python}", "tool.py"], "retry": 0,
        "skip_on_error": True, "track_changes": True,
        "tolerate_restored_changes": True,
    })
    assert stage.retry == 0
    assert stage.skip_on_error is True
    assert stage.track_changes is True
    assert stage.tolerate_restored_changes is True


def test_retry_zero_disables_same_session_retry_and_goes_fresh_then_replan(tmp_path):
    ctx = context(tmp_path); stage = ErrorStage(); fresh = []; executor = StageExecutor(Hooks())
    executor._fresh_session = lambda c: (fresh.append(c.ai_client.session_id), setattr(c.ai_client, "session_id", ""))
    result = executor.run(stage, ctx)
    assert result.status == "replan"
    assert stage.calls == 2
    assert fresh == ["S1"]


def test_skip_on_error_false_never_converts_error_to_pass(tmp_path):
    result = StageExecutor(Hooks()).run(ErrorStage(), context(tmp_path))
    assert result.status == "replan"
    assert result.skipped is False


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
        seen["command"] = command; seen["timeout"] = timeout
        return StageResult(stage, "pass", output="VALID")
    monkeypatch.setattr(module, "run_stage_process", fake)
    stage = create_stage({
        "type":"command", "name":"validate", "status":"validate",
        "result_kind":"validation",
        "command":["{python}","{validator}","{validator_args}"],
    })
    result = stage.run(ctx)
    assert result.status == "pass" and result.output == "VALID"
    assert seen["command"][1] == str(validator)
    assert seen["timeout"] == 10


def test_command_stage_uses_shared_process_boundary(monkeypatch, tmp_path):
    from runner.workflow.stages import command as module
    ctx = context(tmp_path); ctx.config.agent_timeout = 10; seen = {}
    def fake(ctx, stage, command, timeout, label, **kwargs):
        seen["command"] = command
        return StageResult(stage, "pass", output="COMMAND_OK")
    monkeypatch.setattr(module, "run_stage_process", fake)
    stage = create_stage({"type":"command","name":"check","status":"check","command":["tool","--check"]})
    result = stage.run(ctx)
    assert result.status == "pass" and result.output == "COMMAND_OK"
    assert seen["command"] == ["tool", "--check"]
