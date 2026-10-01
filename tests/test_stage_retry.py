from __future__ import annotations

from pathlib import Path

import pytest

from runner.config.defaults import DEFAULT_PER_SESSION_ATTEMPTS, DEFAULT_STAGE_RETRIES
from runner.config.runtime import RuntimeConfig
from runner.errors import ConfigurationError, RunnerError
from runner.runtime.run_state import RunState
from runner.workflow.stages import StageContext, StageResult
from runner.workflow.stages.executor import StageExecutor


class Hooks:
    def before(self, action):
        return []

    def after(self, action, tokens):
        return []

    def change_detector(self, action, tokens, fallback):
        return fallback()


class Model:
    root = Path(".")
    extra_args = []

    def __init__(self):
        self.session_id = "session-A"


class Stage:
    name = "work"
    mode = "readonly"
    actor = "test"
    status = "work"
    detail = ""
    run_state = ""
    track_changes = False
    tolerate_restored_changes = False
    fresh_session_on_start = False

    def __init__(self, results):
        self.results = list(results)
        self.calls: list[str] = []

    def run(self, ctx, previous=None):
        self.calls.append(ctx.ai_client.session_id)
        value = self.results.pop(0)
        if isinstance(value, BaseException):
            raise value
        return StageResult(self.name, value)

    def finish(self, ctx, result):
        return result


class ConfigStage(Stage):
    def run(self, ctx, previous=None):
        raise ConfigurationError("fixed configuration error")


def context(tmp_path: Path, *, retries=DEFAULT_STAGE_RETRIES, delay=0, max_delay=0):
    state = RunState("run", "goal", str(tmp_path))
    model = Model()
    return StageContext(
        config=RuntimeConfig(
            stage_retries=retries,
            retry_delay=delay,
            retry_max_delay=max_delay,
        ),
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


def test_unattended_default_is_unlimited_with_two_same_session_attempts():
    assert DEFAULT_STAGE_RETRIES == -1
    assert DEFAULT_PER_SESSION_ATTEMPTS == 2


def test_global_retry_rotates_session_without_stage_retry_field(tmp_path):
    stage = Stage([
        RunnerError("one"),
        RunnerError("two"),
        RunnerError("three"),
        "pass",
    ])
    ctx = context(tmp_path)

    result = StageExecutor(Hooks()).run(stage, ctx)

    assert result.status == "pass"
    assert stage.calls == ["session-A", "session-A", "", ""]


def test_zero_global_retries_means_one_attempt(tmp_path):
    stage = Stage([RunnerError("no retry")])
    result = StageExecutor(Hooks()).run(stage, context(tmp_path, retries=0))
    assert result.status == "error"
    assert len(stage.calls) == 1


def test_finite_global_retry_budget_is_retries_after_first_attempt(tmp_path):
    stage = Stage([
        RunnerError("one"),
        RunnerError("two"),
        RunnerError("three"),
        RunnerError("four"),
    ])
    result = StageExecutor(Hooks()).run(stage, context(tmp_path, retries=2))
    assert result.status == "error"
    assert len(stage.calls) == 3


def test_per_stage_retry_limit_overrides_global_default(tmp_path):
    stage = Stage([
        RunnerError("one"),
        RunnerError("two"),
        "pass",
    ])
    result = StageExecutor(Hooks()).run(
        stage,
        context(tmp_path, retries=0),
        retry_limit=2,
    )
    assert result.status == "pass"
    assert len(stage.calls) == 3


def test_per_stage_minus_one_keeps_retrying(tmp_path):
    stage = Stage([
        RunnerError("one"),
        RunnerError("two"),
        RunnerError("three"),
        "pass",
    ])
    result = StageExecutor(Hooks()).run(
        stage,
        context(tmp_path, retries=0),
        retry_limit=-1,
    )
    assert result.status == "pass"
    assert len(stage.calls) == 4


def test_configuration_error_fails_closed_without_retry(tmp_path):
    with pytest.raises(ConfigurationError, match="fixed configuration"):
        StageExecutor(Hooks()).run(ConfigStage([]), context(tmp_path))


def test_transient_service_errors_stay_in_same_session_and_backoff_in_seconds(
    tmp_path, monkeypatch
):
    sleeps = []
    monkeypatch.setattr(
        "runner.workflow.stages.executor.sleep_with_heartbeat",
        lambda seconds: sleeps.append(seconds),
    )
    failures = []
    for code in (429, 502, 503):
        error = RunnerError(f"HTTP {code}")
        error.transient = True
        failures.append(error)
    stage = Stage([*failures, "pass"])
    ctx = context(tmp_path, retries=-1, delay=1, max_delay=4)

    result = StageExecutor(Hooks()).run(stage, ctx)

    assert result.status == "pass"
    assert stage.calls == ["session-A"] * 4
    assert sleeps == [1, 2, 4]


def test_error_after_project_change_rotates_session_and_recovers(tmp_path):
    class Changed(Stage):
        def __init__(self):
            super().__init__([])
            self.count = 0

        def run(self, ctx, previous=None):
            self.calls.append(ctx.ai_client.session_id)
            self.count += 1
            if self.count == 1:
                return StageResult(
                    self.name,
                    "error",
                    error=RunnerError("partial side effect"),
                    changed_files=["x.txt"],
                )
            return StageResult(self.name, "pass")

    stage = Changed()
    result = StageExecutor(Hooks()).run(stage, context(tmp_path))
    assert result.status == "pass"
    assert stage.calls == ["session-A", ""]


def test_error_after_project_change_respects_explicit_zero_retry_budget(tmp_path):
    class Changed(Stage):
        def run(self, ctx, previous=None):
            return StageResult(
                self.name,
                "error",
                error=RunnerError("partial side effect"),
                changed_files=["x.txt"],
            )

    stage = Changed([])
    result = StageExecutor(Hooks()).run(stage, context(tmp_path, retries=0))
    assert result.status == "error"
    assert result.changed_files == ["x.txt"]
