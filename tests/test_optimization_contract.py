from __future__ import annotations

from pathlib import Path

from runner.config.runtime import RuntimeConfig
from runner.errors import RunnerError
from runner.runtime.run_state import RunState, Task
from runner.workflow.stages import AIValidatorStage, AIValidatorStageSpec
from runner.workflow.stages.contracts import StageContext
from runner.workflow.stages.executor import StageExecutor


class Hooks:
    def before(self, action):
        return []

    def after(self, action, tokens):
        return []

    def change_detector(self, action, tokens, fallback):
        return fallback()


class FakeAI:
    root = Path(".")
    extra_args = []

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.session_id = ""
        self.calls = []
        self.session_no = 0

    def ask(self, prompt, **kwargs):
        before = self.session_id
        if not self.session_id:
            self.session_no += 1
            self.session_id = f"S{self.session_no}"
        self.calls.append((before, self.session_id, prompt))
        value = self.outputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def set_extra_args(self, extra_args):
        self.extra_args = list(extra_args)


def context(tmp_path, model, **overrides):
    config = RuntimeConfig(
        stage_retries=-1,
        retry_delay=0,
        retry_max_delay=0,
        **overrides,
    )
    state = RunState(
        "run",
        "ORIGINAL SPEC",
        str(tmp_path),
        tasks=[Task("t1", "TODO", "do it", ["ok"], "out")],
    )
    return StageContext(
        config=config,
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=model,
        state_file=tmp_path / "state.json",
        validator_path=None,
        validator_is_ai=True,
        save_state=lambda: None,
        set_stage=lambda stage, detail="": setattr(state, "stage", stage),
    )


def parse_ok(text, ctx):
    if text != "OK":
        raise RunnerError("need OK")
    return {"passed": True}


def test_structured_retry_then_fresh_parser_recovery_keeps_one_stage_contract(tmp_path):
    model = FakeAI(["bad1", "bad2", "bad3", "OK"])
    ctx = context(tmp_path, model)
    ctx.scratch["validator"] = model
    prompt = tmp_path / "validator.md"
    prompt.write_text(
        "Original specification:\n{{ goal }}\nFULL VALIDATOR CONTRACT",
        encoding="utf-8",
    )
    stage = AIValidatorStage(
        AIValidatorStageSpec(
            name="validate_ai",
            session_key="validator",
            prompt=str(prompt),
            parser=parse_ok,
            runs=1,
            required_passes=1,
            structured_retries=2,
            structured_fresh_retries=1,
        )
    )

    result = StageExecutor(Hooks()).run(stage, ctx)

    assert result.status == "pass"
    assert [before for before, _, _ in model.calls] == ["", "S1", "S1", ""]
    assert "FULL VALIDATOR CONTRACT" in model.calls[0][2]
    assert all("FULL VALIDATOR CONTRACT" not in model.calls[i][2] for i in (1, 2))
    assert "FULL VALIDATOR CONTRACT" in model.calls[3][2]


def test_independent_validator_votes_each_start_fresh_session(tmp_path):
    model = FakeAI(["OK", "OK", "OK"])
    ctx = context(
        tmp_path,
        model,
        final_ai_validations=3,
        final_ai_required_passes=2,
    )
    ctx.scratch["validator"] = model
    prompt = tmp_path / "validator.md"
    prompt.write_text("FULL", encoding="utf-8")
    stage = AIValidatorStage(
        AIValidatorStageSpec(
            name="validate_ai",
            session_key="validator",
            prompt=str(prompt),
            parser=parse_ok,
            fresh_session_each_run=True,
        )
    )

    result = stage.run(ctx)

    assert result.status == "pass"
    assert [before for before, _, _ in model.calls] == ["", "", ""]
    assert [after for _, after, _ in model.calls] == ["S1", "S2", "S3"]


def test_validator_vote_threshold_comes_only_from_runtime_config(tmp_path):
    model = FakeAI(["OK", "OK", "BAD"])
    ctx = context(
        tmp_path,
        model,
        final_ai_validations=3,
        final_ai_required_passes=3,
    )
    ctx.scratch["validator"] = model
    prompt = tmp_path / "validator.md"
    prompt.write_text("FULL", encoding="utf-8")

    def parse_vote(text, _ctx):
        return {"passed": text == "OK"}

    stage = AIValidatorStage(
        AIValidatorStageSpec(
            name="validate_ai",
            session_key="validator",
            prompt=str(prompt),
            parser=parse_vote,
            fresh_session_each_run=True,
        )
    )

    result = stage.run(ctx)

    assert result.status == "fail"
    assert '"passes": 2' in result.output
    assert '"required_passes": 3' in result.output


def test_stage_spec_has_no_retry_or_recovery_policy(tmp_path):
    spec = AIValidatorStageSpec(name="validate_ai")
    assert not hasattr(spec, "retry")
    assert not hasattr(spec, "recover")
    assert not hasattr(spec, "restart_at")
