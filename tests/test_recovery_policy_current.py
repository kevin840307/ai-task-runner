from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.config import RuntimeConfig
from runner.config.defaults import DEFAULT_API_WAIT_TIMEOUT, DEFAULT_MAX_ATTEMPTS
from runner.errors import RunnerError
from runner.flow.behavior import _finish_plan, _restart_plan
from runner.flow.stages.base import StageContext, StageResult
from runner.flow.stages.executor import StageExecutor
from runner.flow.stages.global_stage import GlobalStage, GlobalStageSpec
from runner.model import model as model_module
from runner.runtime.state import RunState, Task


class Hooks:
    def before(self, action): return []
    def after(self, action, tokens): return []
    def change_detector(self, action, tokens, fallback): return fallback


class SessionModel:
    root = Path('.')
    extra_args = []
    def __init__(self, failures):
        self.session_id = 'session-A'
        self.failures = list(failures)
        self.calls = []
    def ask(self, prompt, **kwargs):
        self.calls.append((self.session_id, prompt))
        if self.failures:
            error = self.failures.pop(0)
            if error:
                raise error
        if not self.session_id:
            self.session_id = 'session-B'
        return 'ok'
    def set_extra_args(self, extra_args): self.extra_args = list(extra_args)


class AskStage:
    name = 'execute'
    mode = 'write'
    actor = 'executor'
    status = 'execute'
    detail = ''
    retry = None
    run_state = 'executing'
    skip_on_error = False
    tolerate_restored_changes = False
    def run(self, ctx, previous=None):
        return StageResult(self.name, 'pass', output=ctx.model.ask('do current task'))
    def finish(self, ctx, result):
        if result.status == 'pass':
            ctx.save_session()
        return result


class ReviewErrorStage(AskStage):
    name = 'review'
    mode = 'readonly'
    actor = 'model'
    run_state = 'reviewing'
    retry = 2
    skip_on_error = True


class ChangedErrorStage(AskStage):
    def run(self, ctx, previous=None):
        return StageResult.error_result(self.name, RunnerError('bad output')).__class__(
            stage=self.name,
            status='error',
            output='bad output',
            error=RunnerError('bad output'),
            changed_files=['x.txt'],
        )


def context(tmp_path: Path, model, *, retry=2) -> StageContext:
    state = RunState(
        run_id='run-1', goal='ORIGINAL SPEC', project_root=str(tmp_path),
        tasks=[Task('t1', 'Current TODO', 'Do only this TODO', ['must pass'], 'artifact')],
    )
    return StageContext(
        args=RuntimeConfig(task_recovery_threshold=retry, retry_delay=0),
        root=tmp_path,
        work=tmp_path / '.work',
        state=state,
        model=model,
        state_file=tmp_path / 'state.json',
        validator=None,
        ai_validation=False,
        save_state=lambda: None,
        set_stage=lambda stage, detail='': setattr(state, 'stage', stage),
    )


def test_default_non_api_retry_is_two_then_fresh_session(tmp_path):
    assert DEFAULT_MAX_ATTEMPTS == 2
    model = SessionModel([RunnerError('same'), RunnerError('same'), RunnerError('same'), None])
    ctx = context(tmp_path, model)
    result = StageExecutor(Hooks()).run(AskStage(), ctx)
    assert result.status == 'pass'
    assert [session for session, _ in model.calls] == ['session-A', 'session-A', 'session-A', '']
    assert ctx.state.model_session_id == model.session_id == 'session-B'


def test_different_failure_resets_retry_count(tmp_path):
    model = SessionModel([
        RunnerError('failure-A'),
        RunnerError('failure-B'), RunnerError('failure-B'), RunnerError('failure-B'),
        None,
    ])
    ctx = context(tmp_path, model)
    result = StageExecutor(Hooks()).run(AskStage(), ctx)
    assert result.status == 'pass'
    assert [session for session, _ in model.calls] == [
        'session-A', 'session-A', 'session-A', 'session-A', ''
    ]


def test_persistent_same_failure_replans_after_fresh_session(tmp_path):
    model = SessionModel([RunnerError('same')] * 10)
    ctx = context(tmp_path, model)
    result = StageExecutor(Hooks()).run(AskStage(), ctx)
    assert result.status == 'replan'
    assert [session for session, _ in model.calls] == ['session-A', 'session-A', 'session-A', '']

    replanned = _restart_plan(ctx, result)
    assert replanned.replace is True
    assert [item['name'] for item in replanned.stages] == ['planning', 'validate_file', 'validate_ai']
    assert model.session_id == ctx.state.model_session_id == ''


def test_review_retry_then_skip_does_not_count_failures_or_replace_session(tmp_path):
    model = SessionModel([RunnerError('review broke')] * 10)
    ctx = context(tmp_path, model)
    result = StageExecutor(Hooks()).run(ReviewErrorStage(), ctx)
    assert result.status == 'pass' and result.skipped
    assert len(model.calls) == 3  # initial + two retries
    assert all(session == 'session-A' for session, _ in model.calls)
    assert ctx.state.failure_scope == ctx.state.failure_key == ''
    assert ctx.state.same_failures == ctx.state.fresh_session_round == 0


def test_changed_error_is_not_counted_as_failure(tmp_path):
    ctx = context(tmp_path, SessionModel([]))
    result = StageExecutor(Hooks()).run(ChangedErrorStage(), ctx)
    assert result.status == 'error'
    assert result.changed_files == ['x.txt']
    assert ctx.state.failure_scope == ctx.state.failure_key == ''
    assert ctx.state.same_failures == 0


def test_same_session_prompt_is_short_but_fresh_prompt_restores_spec_and_task(tmp_path):
    model = SessionModel([])
    ctx = context(tmp_path, model)
    stage = GlobalStage(GlobalStageSpec(name='execute', status='execute'))
    ctx.execution.previous_error = 'Loop detection halted the run'
    same = stage._same_session_prompt(ctx)
    fresh = stage._fresh_session_prompt(ctx, 'STAGE-SPEC')
    assert 'ORIGINAL SPEC' not in same
    assert 'Do only this TODO' not in same
    assert 'Do not repeat the exact failed action' in same
    assert 'ORIGINAL SPEC' in fresh
    assert 'Current TODO' in fresh and 'Do only this TODO' in fresh
    assert 'Inspect the CURRENT project state first' in fresh
    assert 'STAGE-SPEC' in fresh


def test_plan_returns_execute_review_groups_for_pipeline(tmp_path):
    ctx = context(tmp_path, SessionModel([]))
    tasks = [
        Task('t1', 'one', 'd1', ['a1'], 'o1'),
        Task('t2', 'two', 'd2', ['a2'], 'o2'),
    ]
    result = _finish_plan(ctx, StageResult('planning', 'pass', data=tasks))
    assert [[item['name'] for item in group] for group in result.stages] == [
        ['execute', 'review'], ['execute', 'review']
    ]


def test_api_retry_window_defaults_to_one_hour_and_does_not_use_task_failures(monkeypatch):
    assert DEFAULT_API_WAIT_TIMEOUT == 3600
    ticks = iter([0.0, 1000.0, 2000.0, 3601.0])
    monkeypatch.setattr(model_module.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(model_module.time, 'sleep', lambda _: None)
    calls = 0
    def fail():
        nonlocal calls
        calls += 1
        error = RunnerError('HTTP 503 service unavailable')
        error.transient = True
        raise error
    with pytest.raises(RunnerError, match='503'):
        model_module._call_with_backoff(
            fail, 'api', '', 1, 10, max_elapsed=DEFAULT_API_WAIT_TIMEOUT
        )
    assert calls == 3


def test_service_error_exhaustion_is_not_recorded_as_task_failure(tmp_path):
    error = RunnerError('HTTP 503 service unavailable')
    error.transient = True
    model = SessionModel([error])
    ctx = context(tmp_path, model)
    with pytest.raises(RunnerError, match='503'):
        StageExecutor(Hooks()).run(AskStage(), ctx)
    assert ctx.state.failure_scope == ctx.state.failure_key == ''
    assert ctx.state.same_failures == 0


def test_api_retry_sleep_never_exceeds_remaining_wait_window(monkeypatch):
    ticks = iter([0.0, 3500.0, 3600.0])
    sleeps = []
    monkeypatch.setattr(model_module.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(model_module.time, 'sleep', sleeps.append)
    def fail():
        error = RunnerError('HTTP 503 service unavailable')
        error.transient = True
        raise error
    with pytest.raises(RunnerError):
        model_module._call_with_backoff(fail, 'api', '', 300, 300, max_elapsed=3600)
    assert sleeps == [100.0]
