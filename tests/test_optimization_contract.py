from __future__ import annotations

import os
from pathlib import Path

from runner.config.runtime import RuntimeConfig
from runner.config.defaults import DEFAULT_REVIEW_RETRIES
from runner.errors import RunnerError
from runner.plugins.console import LiveUI
from runner.workflow.stages.contracts import StageContext, StageResult
from runner.workflow.stages.executor import StageExecutor
from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec
from runner.runtime import events
from runner.runtime.run_state import RunState, Task


class Hooks:
    def before(self, action): return []
    def after(self, action, tokens): return []
    def change_detector(self, action, tokens, fallback): return fallback


class FakeAI:
    root = Path('.')
    extra_args = []
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.session_id = ''
        self.calls = []
        self.session_no = 0
    def ask(self, prompt, **kwargs):
        before = self.session_id
        if not self.session_id:
            self.session_no += 1
            self.session_id = f'S{self.session_no}'
        self.calls.append((before, self.session_id, prompt))
        value = self.outputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value
    def run_with_retry(self, action, *args, **kwargs): return action()
    def set_extra_args(self, extra_args): self.extra_args = list(extra_args)


class Stdout:
    def __init__(self, tty=True): self.tty, self.output = tty, ''
    def isatty(self): return self.tty
    def write(self, text): self.output += text
    def flush(self): pass


def ctx(tmp_path, model, **config):
    state = RunState('run', 'ORIGINAL SPEC', str(tmp_path), tasks=[Task('t1','TODO','do it',['ok'],'out')])
    return StageContext(
        config=RuntimeConfig(stage_retry_delay=0, **config), root=tmp_path, work=tmp_path/'.work',
        state=state, ai_client=model, state_file=tmp_path/'state.json', validator_path=None,
        validator_is_ai=True, save_state=lambda: None,
        set_stage=lambda stage, detail='': setattr(state, 'stage', stage),
    )


def parse_ok(text, ctx):
    if text != 'OK': raise RunnerError('need OK')
    return {'passed': True}


def test_structured_retry_stays_short_then_fresh_retry_restores_full_context(tmp_path):
    model = FakeAI(['bad1', 'bad2', 'bad3', 'OK'])
    c = ctx(tmp_path, model)
    c.scratch['validator'] = model
    prompt = tmp_path / 'validator.md'
    prompt.write_text(
        'Original specification:\n{{ goal }}\nFULL VALIDATOR CONTRACT',
        encoding='utf-8',
    )
    stage = BaseStage(BaseStageSpec(
        name='validate_ai', status='validate', client_cache_key='validator',
        prompt=str(prompt), parser=parse_ok,
        result_status=lambda data: 'pass', structured_retries=2, structured_fresh_retries=1, retry=0,
    ))
    result = StageExecutor(Hooks()).run(stage, c)
    assert result.status == 'pass'
    assert [before for before, _, _ in model.calls] == ['', 'S1', 'S1', '']
    assert 'Original specification:\nORIGINAL SPEC' in model.calls[0][2]
    assert 'FULL VALIDATOR CONTRACT' in model.calls[0][2]
    assert all('FULL VALIDATOR CONTRACT' not in model.calls[i][2] for i in (1,2))
    assert 'Original specification:\nORIGINAL SPEC' in model.calls[3][2]
    assert model.calls[3][2].count('Original specification:\nORIGINAL SPEC') == 1
    assert 'Stage instructions:\nOriginal specification:' in model.calls[3][2]


def test_independent_ai_votes_each_start_new_session(tmp_path):
    model = FakeAI(['OK', 'OK', 'OK'])
    c = ctx(tmp_path, model)
    c.scratch['validator'] = model
    prompt = tmp_path / 'validator.md'
    prompt.write_text('FULL', encoding='utf-8')
    stage = BaseStage(BaseStageSpec(
        name='validate_ai', status='validate', client_cache_key='validator', runs=3,
        fresh_session_each_run=True, prompt=str(prompt), parser=parse_ok,
        result_status=lambda data: 'pass',
    ))
    result = stage.run(c)
    assert result.status == 'pass'
    assert [before for before, _, _ in model.calls] == ['', '', '']
    assert [after for _, after, _ in model.calls] == ['S1','S2','S3']


def test_ai_vote_recovery_preserves_three_distinct_successful_sessions(tmp_path):
    model = FakeAI([RunnerError('backend failed'), 'OK', 'OK', 'OK'])
    c = ctx(tmp_path, model, same_session_retries=2)
    c.scratch['validator'] = model
    prompt = tmp_path / 'validator-recovery.md'
    prompt.write_text('FULL', encoding='utf-8')
    stage = BaseStage(BaseStageSpec(
        name='validate_ai', status='validate', client_cache_key='validator', runs=3,
        fresh_session_each_run=True, prompt=str(prompt), parser=parse_ok,
        result_status=lambda data: 'pass', retry=-1,
    ))

    result = StageExecutor(Hooks()).run(stage, c)

    assert result.status == 'pass'
    successful_sessions = [after for _, after, _ in model.calls[1:]]
    assert successful_sessions == ['S1', 'S2', 'S3']


def test_ai_vote_recovery_does_not_repeat_completed_votes(tmp_path):
    model = FakeAI(['OK', RunnerError('backend failed'), 'OK', 'OK'])
    c = ctx(tmp_path, model, same_session_retries=2)
    c.scratch['validator'] = model
    prompt = tmp_path / 'validator-partial-recovery.md'
    prompt.write_text('FULL', encoding='utf-8')
    stage = BaseStage(BaseStageSpec(
        name='validate_ai', status='validate', client_cache_key='validator', runs=3,
        fresh_session_each_run=True, prompt=str(prompt), parser=parse_ok,
        result_status=lambda data: 'pass', retry=-1,
    ))

    result = StageExecutor(Hooks()).run(stage, c)

    assert result.status == 'pass'
    assert len(model.calls) == 4
    assert [after for _, after, _ in model.calls] == ['S1', 'S2', 'S2', 'S3']


def test_ai_vote_hook_violation_discards_votes_from_rejected_attempt(tmp_path):
    from runner.plugins.contracts import HookViolation

    class RejectFirstAttempt(Hooks):
        def __init__(self):
            self.calls = 0

        def after(self, action, tokens):
            self.calls += 1
            return [HookViolation('restored change')] if self.calls == 1 else []

    model = FakeAI(['OK', RunnerError('backend failed'), 'OK', 'OK', 'OK'])
    c = ctx(tmp_path, model, same_session_retries=2)
    c.scratch['validator'] = model
    prompt = tmp_path / 'validator-rejected-attempt.md'
    prompt.write_text('FULL', encoding='utf-8')
    stage = BaseStage(BaseStageSpec(
        name='validate_ai', status='validate', client_cache_key='validator', runs=3,
        fresh_session_each_run=True, prompt=str(prompt), parser=parse_ok,
        result_status=lambda data: 'pass', retry=-1,
    ))

    result = StageExecutor(RejectFirstAttempt()).run(stage, c)

    assert result.status == 'pass'
    assert len(model.calls) == 5
    assert [after for _, after, _ in model.calls[-3:]] == ['S3', 'S4', 'S5']


class ReviewStage:
    name='review'; mode='readonly'; actor='model'; status='review'; detail=''; run_state='reviewing'
    retry=None; retry_attr='review_retries'; skip_on_error=True; tolerate_restored_changes=False
    def run(self, c, previous=None):
        c.ai_client.ask('review')
        return StageResult('review','pass')
    def finish(self,c,r): return r


def test_review_default_is_one_retry_then_skip(tmp_path):
    assert DEFAULT_REVIEW_RETRIES == 1
    model=FakeAI([RunnerError('x'), RunnerError('x')])
    c=ctx(tmp_path, model, review_retries=1)
    result=StageExecutor(Hooks()).run(ReviewStage(), c)
    assert result.status == 'pass' and result.skipped
    assert len(model.calls) == 2
    assert c.state.same_failures == 0


def test_review_zero_disables_skip_and_uses_normal_recovery(tmp_path):
    model=FakeAI([RunnerError('x'), RunnerError('x')])
    model.session_id='S0'
    c=ctx(tmp_path, model, review_retries=0)
    result=StageExecutor(Hooks()).run(ReviewStage(), c)
    assert result.status == 'replan' and not result.skipped
    assert len(model.calls) == 2
    assert model.calls[0][0] == 'S0' and model.calls[1][0] == ''


def test_task_list_update_stops_old_spinner_without_redrawing_old_status(monkeypatch, tmp_path):
    stdout=Stdout(True)
    monkeypatch.setattr('runner.plugins.console.sys.stdout', stdout)
    monkeypatch.setattr('runner.plugins.console.supports_ansi_screen', lambda: False)
    monkeypatch.setattr('runner.plugins.console.shutil.get_terminal_size', lambda fallback: os.terminal_size((120,20)))
    ui=LiveUI()
    empty=RunState('run','goal',str(tmp_path))
    ui.bind(empty)
    ui.start('PLANNING')
    state=RunState('run','goal',str(tmp_path), tasks=[Task('t1','one','d',['a'],'o')])
    ui.bind(state)
    ui.stop()
    tail=stdout.output[stdout.output.rfind('AI Task Runner'):]
    assert 'PLANNING' not in tail
    assert '[>] 1. one' in tail


def test_progress_no_longer_publishes_runner_control(tmp_path):
    records=[]
    bus=events.EventBus(); bus.subscribe(records.append); events.configure(bus)
    events.bind(RunState('run','goal',str(tmp_path)))
    events.stop()
    assert all(event['type'] != 'runner.control' for event in records)
    assert any(event['type']=='runner.status' and event['action']=='stop' for event in records)

def test_ai_validator_votes_use_independent_new_sessions(tmp_path, monkeypatch):
    import json, sys
    from runner.api import RunRequest, run
    root = Path(__file__).resolve().parents[1]
    state_dir = tmp_path.parent / 'v6-votes-state'
    monkeypatch.setenv('SCENARIO', 'happy_path')
    monkeypatch.setenv('SCENARIO_STATE_DIR', str(state_dir))
    request = RunRequest(
        goal='Create requested result', project_root=str(tmp_path), validator='ai',
        backend='qwen', command=f'"{sys.executable}" "{root / "tests/scenario_agent.py"}"',
        final_ai_validations=3, retry_delay=0, retry_wait=0, retry_max_wait=0,
        api_wait_timeout=10, agent_idle_after_change_timeout=0,
    )
    result = run(request)
    records = [json.loads(line) for line in (state_dir/'prompt-log.jsonl').read_text().splitlines()]
    votes = [item for item in records if item['stage'] == 'validator']
    assert result.completed and len(votes) == 3
    assert all(not item['resumed'] for item in votes)

def test_ai_vote_required_passes_uses_runtime_config(tmp_path):
    model = FakeAI(['OK', 'OK', 'BAD'])
    c = ctx(tmp_path, model, final_ai_validations=3, final_ai_required_passes=3)
    c.scratch['validator'] = model
    prompt = tmp_path / 'validator-required.md'
    prompt.write_text('FULL', encoding='utf-8')

    def parse_vote(text, _ctx):
        return {'passed': text == 'OK'}

    stage = BaseStage(BaseStageSpec(
        name='validate_ai', status='validate', client_cache_key='validator',
        runs_field='final_ai_validations', required_passes_field='final_ai_required_passes',
        fresh_session_each_run=True, prompt=str(prompt), parser=parse_vote,
        result_status=lambda data: 'pass' if data['passed'] else 'fail',
    ))
    result = stage.run(c)
    assert result.status == 'fail'
    assert '"passes": 2' in result.output
    assert '"required_passes": 3' in result.output
