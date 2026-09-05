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
    retry_attr = ""
    skip_on_error = False
    track_changes = False
    tolerate_restored_changes = False

    def __init__(self):
        self.calls = 0

    def run(self, ctx, previous=None):
        self.calls += 1
        raise RunnerError("boom")

    def finish(self, ctx, result):
        return result


def context(tmp_path: Path) -> StageContext:
    state = RunState("run", "goal", str(tmp_path))
    ai = SimpleNamespace(session_id="S1")
    return StageContext(
        config=RuntimeConfig(same_session_retries=2, stage_retry_delay=0),
        root=tmp_path,
        work=tmp_path / ".work",
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
    assert StageAction(stage, SimpleNamespace(root=Path('.'), work=Path('.'))).track_changes is True


def test_python_stage_specs_expose_common_execution_capabilities():
    catalog = stage_catalog()
    options = {item["name"] for item in catalog["python"]["options"]}
    assert {"retry", "retry_attr", "skip_on_error", "track_changes", "tolerate_restored_changes"} <= options


def test_python_stage_receives_common_execution_capabilities():
    stage = create_stage({
        "type": "python",
        "name": "script",
        "status": "script",
        "path": "tool.py",
        "retry": 0,
        "retry_attr": "review_retries",
        "skip_on_error": True,
        "track_changes": True,
        "tolerate_restored_changes": True,
    })
    assert stage.retry == 0
    assert stage.retry_attr == "review_retries"
    assert stage.skip_on_error is True
    assert stage.track_changes is True
    assert stage.tolerate_restored_changes is True


def test_retry_zero_disables_same_session_retry_and_goes_fresh_then_replan(tmp_path):
    ctx = context(tmp_path)
    stage = ErrorStage()
    fresh = []
    executor = StageExecutor(Hooks())
    executor._fresh_session = lambda c: (fresh.append(c.ai_client.session_id), setattr(c.ai_client, "session_id", ""))

    result = executor.run(stage, ctx)

    assert result.status == "replan"
    assert stage.calls == 2  # initial + one fresh-session attempt, no same-session retry
    assert fresh == ["S1"]


def test_skip_on_error_false_never_converts_error_to_pass(tmp_path):
    ctx = context(tmp_path)
    stage = ErrorStage()
    result = StageExecutor(Hooks()).run(stage, ctx)
    assert result.status == "replan"
    assert result.skipped is False


def test_python_file_validator_receives_common_execution_capabilities():
    stage = create_stage({
        "type": "python",
        "name": "validate",
        "status": "validate",
        "path": "validate.py",
        "validator": "file",
        "retry": 1,
        "retry_attr": "review_retries",
        "skip_on_error": True,
        "track_changes": True,
        "tolerate_restored_changes": True,
    })
    assert stage.retry == 1
    assert stage.retry_attr == "review_retries"
    assert stage.skip_on_error is True
    assert stage.track_changes is True
    assert stage.tolerate_restored_changes is True


def test_python_file_validator_run_uses_process_result(monkeypatch, tmp_path):
    from runner.workflow.stages import python_stage as module

    validator = tmp_path / "validate.py"
    validator.write_text("print('ok')", encoding="utf-8")
    ctx = context(tmp_path)
    ctx.work.mkdir()
    ctx.config.validator_args = []
    ctx.config.validator_timeout = 10
    monkeypatch.setattr(module, "run_python", lambda *args, **kwargs: SimpleNamespace(return_code=0, output="VALID"))

    stage = create_stage({"type": "python", "name": "validate", "status": "validate", "validator": "file", "path": str(validator)})
    result = stage.run(ctx)

    assert result.status == "pass"
    assert result.output == "VALID"


def test_generic_python_run_uses_process_result(monkeypatch, tmp_path):
    from runner.workflow.stages import python_stage as module

    ctx = context(tmp_path)
    ctx.config.agent_timeout = 10
    monkeypatch.setattr(module, "run_python", lambda *args, **kwargs: SimpleNamespace(return_code=1, output="FAIL"))
    stage = create_stage({"type": "python", "name": "script", "status": "script", "path": "tool.py"})

    result = stage.run(ctx)

    assert result.status == "fail"
    assert result.output == "FAIL"


def test_python_file_validator_and_ai_validator_are_distinct_stages(tmp_path):
    from runner.workflow.loader import load_workflow
    from runner.workflow.stages import BaseStage, PythonStage

    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
stages:
  validate_file:
    type: python
    validator: file
    status: File validate
  validate_ai:
    validator: ai
    status: AI validate
    backend_mode: review
flow: [validate_file, validate_ai]
""",
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_file)
    file_stage = create_stage(workflow[0])
    ai_stage = create_stage(workflow[1])

    assert isinstance(file_stage, PythonStage)
    assert file_stage.spec.validator == "file"
    assert isinstance(ai_stage, BaseStage)
    assert file_stage is not ai_stage


def test_generic_python_does_not_inherit_validator_conventions():
    stage = create_stage({
        "type": "python",
        "name": "script",
        "status": "Run script",
        "path": "tool.py",
        "args": ["--mode", "check"],
    })
    assert stage.spec.validator == ""
    assert stage.spec.timeout_attr == "agent_timeout"
    assert stage.spec.args == ["--mode", "check"]
