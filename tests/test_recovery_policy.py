from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.config import RuntimeConfig
from runner.config.defaults import DEFAULT_API_WAIT_TIMEOUT, DEFAULT_MAX_ATTEMPTS
from runner.errors import RunnerError
from runner.workflow.rules import handle_plan_result, prepare_replan
from runner.workflow.stages.contracts import StageContext, StageResult
from runner.workflow.stages.executor import StageExecutor
from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec
import runner.ai.client as ai_client_module
from runner.runtime.run_state import RunState, Task


class Hooks:
    def before(self, action): return []
    def after(self, action, tokens): return []
    def change_detector(self, action, tokens, fallback): return fallback


class SessionFakeAI:
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
        return StageResult(self.name, 'pass', output=ctx.ai_client.ask('do current task'))
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


class UnlimitedValidationStage(AskStage):
    name = 'validate_ai'
    mode = 'readonly'
    actor = 'validator'
    run_state = 'validating'
    retry = -1


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
        config=RuntimeConfig(same_session_retries=retry, stage_retry_delay=0),
        root=tmp_path,
        work=tmp_path / '.work',
        state=state,
        ai_client=model,
        state_file=tmp_path / 'state.json',
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda stage, detail='': setattr(state, 'stage', stage),
    )


def test_default_non_api_retry_is_two_then_fresh_session(tmp_path):
    assert DEFAULT_MAX_ATTEMPTS == 2
    model = SessionFakeAI([RunnerError('same'), RunnerError('same'), RunnerError('same'), None])
    ctx = context(tmp_path, model)
    result = StageExecutor(Hooks()).run(AskStage(), ctx)
    assert result.status == 'pass'
    assert [session for session, _ in model.calls] == ['session-A', 'session-A', 'session-A', '']
    assert ctx.state.ai_session_id == model.session_id == 'session-B'


def test_unlimited_validation_keeps_default_same_then_fresh_recovery(tmp_path):
    model = SessionFakeAI([RunnerError('same')] * 3 + [None])
    ctx = context(tmp_path, model)
    result = StageExecutor(Hooks()).run(UnlimitedValidationStage(), ctx)
    assert result.status == 'pass'
    assert [session for session, _ in model.calls] == [
        'session-A', 'session-A', 'session-A', ''
    ]


def test_unlimited_validation_continues_after_a_failed_fresh_round(tmp_path):
    model = SessionFakeAI([RunnerError('same')] * 7 + [None])
    ctx = context(tmp_path, model)
    result = StageExecutor(Hooks()).run(UnlimitedValidationStage(), ctx)
    assert result.status == 'pass'
    assert len(model.calls) == 8


def test_different_failure_resets_retry_count(tmp_path):
    model = SessionFakeAI([
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
    model = SessionFakeAI([RunnerError('same')] * 10)
    ctx = context(tmp_path, model)
    result = StageExecutor(Hooks()).run(AskStage(), ctx)
    assert result.status == 'replan'
    assert [session for session, _ in model.calls] == ['session-A', 'session-A', 'session-A', '']

    replanned = prepare_replan(ctx, result)
    assert replanned.status == 'replan'
    assert ctx.state.workflow_position == 0
    assert model.session_id == ctx.state.ai_session_id == ''


def test_review_retry_then_skip_does_not_count_failures_or_replace_session(tmp_path):
    model = SessionFakeAI([RunnerError('review broke')] * 10)
    ctx = context(tmp_path, model)
    result = StageExecutor(Hooks()).run(ReviewErrorStage(), ctx)
    assert result.status == 'pass' and result.skipped
    assert len(model.calls) == 3  # initial + two retries
    assert all(session == 'session-A' for session, _ in model.calls)
    assert ctx.state.failure_scope == ctx.state.failure_key == ''
    assert ctx.state.same_failures == ctx.state.fresh_session_round == 0


def test_changed_error_is_not_counted_as_failure(tmp_path):
    ctx = context(tmp_path, SessionFakeAI([]))
    result = StageExecutor(Hooks()).run(ChangedErrorStage(), ctx)
    assert result.status == 'error'
    assert result.changed_files == ['x.txt']
    assert ctx.state.failure_scope == ctx.state.failure_key == ''
    assert ctx.state.same_failures == 0


def test_same_session_prompt_is_short_and_fresh_wrapper_does_not_duplicate_context(tmp_path):
    model = SessionFakeAI([])
    ctx = context(tmp_path, model)
    stage = BaseStage(BaseStageSpec(name='execute', status='execute'))
    ctx.execution.previous_error = 'Loop detection halted the run'
    same = stage._same_session_prompt(ctx)
    original = 'ORIGINAL SPEC\nCurrent TODO\nDo only this TODO\nSTAGE-SPEC'
    fresh = stage._fresh_session_prompt(original)
    assert 'ORIGINAL SPEC' not in same
    assert 'Do only this TODO' not in same
    assert 'Do not repeat the exact failed action' in same
    assert fresh.count('ORIGINAL SPEC') == 1
    assert fresh.count('Current TODO') == 1
    assert fresh.count('Do only this TODO') == 1
    assert 'Inspect the CURRENT project state first' in fresh
    assert 'STAGE-SPEC' in fresh


def test_plan_installs_tasks_without_expanding_task_flows(tmp_path):
    ctx = context(tmp_path, SessionFakeAI([]))
    tasks = [
        Task('t1', 'one', 'd1', ['a1'], 'o1'),
        Task('t2', 'two', 'd2', ['a2'], 'o2'),
    ]
    result = handle_plan_result(ctx, StageResult('planning', 'pass', data=tasks))
    assert result.status == 'pass'
    assert ctx.state.tasks == tasks
    assert ctx.state.current == 0
    assert ctx.state.dynamic_steps == []
    assert ctx.state.dynamic_index == 0


def test_api_retry_window_defaults_to_one_hour_and_does_not_use_task_failures(monkeypatch):
    assert DEFAULT_API_WAIT_TIMEOUT == 3600
    ticks = iter([0.0, 1000.0, 2000.0, 3601.0])
    monkeypatch.setattr(ai_client_module.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(ai_client_module.time, 'sleep', lambda _: None)
    calls = 0
    def fail():
        nonlocal calls
        calls += 1
        error = RunnerError('HTTP 503 service unavailable')
        error.transient = True
        raise error
    with pytest.raises(RunnerError, match='503'):
        ai_client_module._run_with_backoff(
            fail, 'api', '', 1, 10, max_elapsed=DEFAULT_API_WAIT_TIMEOUT
        )
    assert calls == 3


def test_service_error_exhaustion_is_not_recorded_as_task_failure(tmp_path):
    error = RunnerError('HTTP 503 service unavailable')
    error.transient = True
    model = SessionFakeAI([error])
    ctx = context(tmp_path, model)
    with pytest.raises(RunnerError, match='503'):
        StageExecutor(Hooks()).run(AskStage(), ctx)
    assert ctx.state.failure_scope == ctx.state.failure_key == ''
    assert ctx.state.same_failures == 0


def test_api_retry_sleep_never_exceeds_remaining_wait_window(monkeypatch):
    ticks = iter([0.0, 3500.0, 3600.0])
    sleeps = []
    monkeypatch.setattr(ai_client_module.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(ai_client_module.time, 'sleep', sleeps.append)
    def fail():
        error = RunnerError('HTTP 503 service unavailable')
        error.transient = True
        raise error
    with pytest.raises(RunnerError):
        ai_client_module._run_with_backoff(fail, 'api', '', 300, 300, max_elapsed=3600)
    assert sleeps == [100.0]
