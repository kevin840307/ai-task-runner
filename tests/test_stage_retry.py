from __future__ import annotations

from pathlib import Path

import pytest

from runner.config.defaults import (
    DEFAULT_PER_SESSION_ATTEMPTS,
    DEFAULT_STAGE_RETRIES,
)
from runner.config.runtime import RuntimeConfig
from runner.errors import ConfigurationError, RunnerError
from runner.runtime.run_state import RunState
from runner.workflow.stages.contracts import StageContext, StageResult
from runner.workflow.stages.executor import StageExecutor


class Hooks:
    def before(self, action):
        return []

    def after(self, action, tokens):
        return []

    def change_detector(self, action, tokens, fallback):
        return fallback


class Model:
    root = Path(".")
    extra_args = []

    def __init__(self, failures):
        self.session_id = "session-A"
        self.failures = list(failures)
        self.calls = []

    def ask(self, prompt, **kwargs):
        self.calls.append(self.session_id)
        if self.failures:
            error = self.failures.pop(0)
            if error is not None:
                raise error
        if not self.session_id:
            self.session_id = "session-B"
        return "ok"


class AskStage:
    name = "execute"
    mode = "write"
    actor = "executor"
    status = "execute"
    detail = ""
    run_state = "executing"
    retry = None
    tolerate_restored_changes = False
    track_changes = False
    fresh_session_on_start = False

    def run(self, ctx, previous=None):
        return StageResult(self.name, "pass", output=ctx.ai_client.ask("work"))

    def finish(self, ctx, result):
        if result.status == "pass":
            ctx.save_session()
        return result


class NoRetryStage(AskStage):
    retry = 0


class ThreeRetryStage(AskStage):
    retry = 3


class ChangedErrorStage(AskStage):
    def run(self, ctx, previous=None):
        return StageResult(
            self.name,
            "error",
            output="changed then failed",
            error=RunnerError("changed then failed"),
            changed_files=["x.txt"],
        )


class ConfigErrorStage(AskStage):
    def run(self, ctx, previous=None):
        raise ConfigurationError("invalid fixed configuration")


def context(tmp_path: Path, model, *, retries=DEFAULT_STAGE_RETRIES) -> StageContext:
    state = RunState("run", "goal", str(tmp_path))
    return StageContext(
        config=RuntimeConfig(stage_retries=retries, stage_retry_delay=0),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=model,
        state_file=tmp_path / ".work" / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda stage, detail="": setattr(state, "stage", stage),
    )


def test_unattended_default_is_unlimited():
    assert DEFAULT_STAGE_RETRIES == -1
    assert DEFAULT_PER_SESSION_ATTEMPTS == 2


def test_unlimited_retry_rotates_fresh_session_and_eventually_passes(tmp_path):
    model = Model([
        RunnerError("temporary"),
        RunnerError("temporary"),
        RunnerError("temporary"),
        None,
    ])
    result = StageExecutor(Hooks()).run(AskStage(), context(tmp_path, model))

    assert result.status == "pass"
    assert model.calls == ["session-A", "session-A", "", ""]
    assert model.session_id == "session-B"


def test_zero_retry_means_one_attempt_only(tmp_path):
    model = Model([RunnerError("temporary"), None])
    result = StageExecutor(Hooks()).run(
        NoRetryStage(),
        context(tmp_path, model),
    )

    assert result.status == "error"
    assert model.calls == ["session-A"]


def test_finite_retry_budget_counts_total_retries(tmp_path):
    model = Model([
        RunnerError("one"),
        RunnerError("two"),
        RunnerError("three"),
        RunnerError("four"),
        None,
    ])
    result = StageExecutor(Hooks()).run(
        ThreeRetryStage(),
        context(tmp_path, model),
    )

    assert result.status == "error"
    assert len(model.calls) == 4
    assert model.calls[:2] == ["session-A", "session-A"]
    assert model.calls[2:] == ["", ""]


def test_configuration_error_fails_closed_without_retry(tmp_path):
    model = Model([])
    with pytest.raises(ConfigurationError, match="invalid fixed configuration"):
        StageExecutor(Hooks()).run(
            ConfigErrorStage(),
            context(tmp_path, model),
        )


def test_transient_service_error_escapes_to_outer_supervisor(tmp_path):
    error = RunnerError("HTTP 503 service unavailable")
    error.transient = True
    model = Model([error])

    with pytest.raises(RunnerError, match="503"):
        StageExecutor(Hooks()).run(
            AskStage(),
            context(tmp_path, model),
        )

    assert model.calls == ["session-A"]


def test_changed_error_is_not_blindly_retried(tmp_path):
    model = Model([])
    result = StageExecutor(Hooks()).run(
        ChangedErrorStage(),
        context(tmp_path, model),
    )

    assert result.status == "error"
    assert result.changed_files == ["x.txt"]
