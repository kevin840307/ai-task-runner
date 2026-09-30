from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_task_runner import parser
from runner.agent.opencode import OpenCodeBackend
from runner.agent.qwen import QwenBackend
from runner.config.runtime import RuntimeConfig
from runner.config.defaults import (
    DEFAULT_STAGE_RETRIES,
    DEFAULT_WATCHDOG_INTERVAL,
    DEFAULT_WORKER_HANG_TIMEOUT,
)
from runner.errors import RunnerError
from runner.plugins.console import LiveUI
from runner.workflow.stages import StageContext, StageResult
from runner.workflow.stages.executor import StageExecutor
from runner.agent import AIClient, BackendResult
from runner.runtime import events
from runner.runtime.run_state import RunState


def _backend(cls):
    value = object.__new__(cls)
    value.base_command = [cls.name]
    value.extra_args = []
    value.root = Path('.')
    return value


def _state(tmp_path: Path) -> RunState:
    return RunState(run_id='run-1', goal='x', project_root=str(tmp_path))


def test_model_prompts_are_stdin_not_argv():
    prompt = 'x' * 100_000
    for cls in (QwenBackend, OpenCodeBackend):
        backend = _backend(cls)
        assert backend.stdin_prompt(prompt) == prompt
        assert prompt not in backend.build_command(prompt, '')
    qwen = _backend(QwenBackend)
    assert '--resume' in qwen.build_command('x', 'session-A')
    assert '--resume' not in qwen.build_command('x', '')


def test_watchdog_default_is_configurable_15_seconds():
    args = parser().parse_args(['--goal', 'x', '--validator', 'ai'])
    assert args.watchdog_interval == DEFAULT_WATCHDOG_INTERVAL == 15.0
    assert parser().parse_args([
        '--goal', 'x', '--validator', 'ai', '--watchdog-interval', '3'
    ]).watchdog_interval == 3



def test_worker_hang_timeout_defaults_to_10_minutes_and_is_configurable():
    args = parser().parse_args(["--goal", "x", "--validator", "ai"])
    assert args.worker_hang_timeout == DEFAULT_WORKER_HANG_TIMEOUT == 600.0

    configured = parser().parse_args([
        "--goal", "x", "--validator", "ai",
        "--worker-hang-timeout", "1800",
    ])
    assert configured.worker_hang_timeout == 1800.0

    disabled = parser().parse_args([
        "--goal", "x", "--validator", "ai",
        "--worker-hang-timeout", "0",
    ])
    assert disabled.worker_hang_timeout == 0.0


def test_runtime_rejects_negative_worker_hang_timeout():
    config = RuntimeConfig(
        goal="x",
        project_root=".",
        validator="ai",
        worker_hang_timeout=-1,
    )
    with pytest.raises(ValueError, match="worker_hang_timeout"):
        config.validate()


def test_plain_console_deduplicates_same_status(tmp_path, capsys):
    ui = LiveUI()
    ui.enabled = True
    ui.fullscreen = False
    ui.bind(_state(tmp_path))
    capsys.readouterr()
    ui.set('working')
    ui.set('working')
    output = capsys.readouterr().out
    assert output.count('working') == 1
    assert ui._thread is None


def test_stage_retry_limit_is_one_public_retry_setting():
    args = parser().parse_args(['--goal', 'x', '--validator', 'ai'])
    assert args.stage_retries == DEFAULT_STAGE_RETRIES == -1

    RuntimeConfig(goal='x', validator='ai', stage_retries=-1).validate()
    with pytest.raises(ValueError, match='must be -1'):
        RuntimeConfig(goal='x', validator='ai', stage_retries=-2).validate()


class _Hooks:
    def before(self, action): return []
    def after(self, action, tokens): return []
    def change_detector(self, action, tokens, fallback): return fallback


class _SessionModel:
    root = Path('.')
    extra_args = []

    def __init__(self):
        self.session_id = 'session-A'
        self.calls = []

    def ask(self, prompt, **kwargs):
        self.calls.append(self.session_id)
        if len(self.calls) <= 2:
            raise RunnerError('Loop detection halted the run: consecutive_identical_tool_calls')
        self.session_id = 'session-B'
        return 'ok'

    def set_extra_args(self, extra_args):
        self.extra_args = list(extra_args)


class _ModelStage:
    name = 'understand'
    mode = 'readonly'
    actor = 'model'
    status = 'understand'
    detail = ''
    run_state = 'planning'
    tolerate_restored_changes = False

    def run(self, ctx, previous=None):
        return StageResult(self.name, 'pass', output=ctx.ai_client.ask('understand'))

    def finish(self, ctx, result):
        ctx.save_session()
        return result


def test_fresh_recovery_really_drops_old_session_and_accepts_new_session(tmp_path):
    state = _state(tmp_path)
    model = _SessionModel()
    saves = []
    ctx = StageContext(
        config=RuntimeConfig(stage_retries=2, retry_delay=0),
        root=tmp_path,
        work=tmp_path / '.work',
        state=state,
        ai_client=model,
        state_file=tmp_path / 'state.json',
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: saves.append(state.dump()),
        set_stage=lambda stage, detail='': setattr(state, 'stage', stage),
    )

    result = StageExecutor(_Hooks()).run(_ModelStage(), ctx)

    assert result.status == 'pass'
    assert model.calls == ['session-A', 'session-A', '']  # Fresh Session only after two same-session failures
    assert model.session_id == state.ai_session_id == 'session-B'


def test_model_result_event_contains_actual_new_session(tmp_path, monkeypatch):
    client = AIClient('qwen', sys.executable, tmp_path, [])

    class Backend:
        name = 'qwen'
        base_command = [sys.executable]
        root = tmp_path
        extra_args = []
        timeout = 30
        def ask(self, prompt, session_id, idle_timeout_after_change, change_detected):
            assert session_id == ''
            return BackendResult('ok', 'new-session-42')
        def prepare_project(self): return []

    client._backend = Backend()
    events = []
    monkeypatch.setattr(client, '_publish_ai_event', lambda kind, session_id, text, call_id='', error='', **meta: (events.append((kind, session_id, meta)) or 'call-1'))

    assert client.ask('hello') == 'ok'
    assert events[0][0:2] == ('model.prompt', '')
    assert events[0][2]['session_mode'] == 'new'
    assert events[-1][0:2] == ('model.result', 'new-session-42')
    assert events[-1][2]['previous_session'] == ''


def test_console_observer_ignores_duplicate_stage_start_event(tmp_path):
    from runner.plugins.console import ConsoleObserver
    runtime = SimpleNamespace(config=SimpleNamespace(human_output=False))
    observer = ConsoleObserver(runtime)
    calls = []
    observer.ui.start = lambda status, detail='': calls.append((status, detail))
    event = {'state': _state(tmp_path), 'status': 'working', 'detail': '', 'action': 'start'}
    observer({**event, 'type': 'runner.stage'})
    observer({**event, 'type': 'runner.status'})
    assert calls == [('working', '')]


def test_watchdog_interval_does_not_delay_process_exit(tmp_path):
    import subprocess
    import time
    from runner.runtime.process_runner import _communicate_bounded

    process = subprocess.Popen(
        [sys.executable, "-c", "print('ok')"],
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    started = time.monotonic()
    result = _communicate_bounded(
        process,
        timeout=10,
        idle_timeout_after_change=10,
        change_detected=lambda: False,
        input_text=None,
        watchdog_interval=15,
    )
    assert result.return_code == 0
    assert result.output.strip() == "ok"
    assert time.monotonic() - started < 5


def test_cleanup_stale_safety_snapshots(tmp_path):
    from runner.workspace import cleanup_stale_artifacts

    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    readonly = temp_root / "ai-task-runner-readonly-old"
    protected = temp_root / "ai-task-runner-protect-old"
    keep = temp_root / "unrelated"
    for path in (readonly, protected, keep):
        path.mkdir()
        (path / "x.txt").write_text("x", encoding="utf-8")

    cleanup_stale_artifacts(tmp_path / "work", temp_root=temp_root, older_than=0)

    assert not readonly.exists()
    assert not protected.exists()
    assert keep.exists()


def test_run_process_applies_backend_environment_overrides(tmp_path):
    from runner.runtime.process_runner import run_process

    code = "import os; print(os.environ.get('RUNNER_BACKEND_TEST', 'missing'))"
    result = run_process(
        [sys.executable, "-c", code],
        tmp_path,
        10,
        environment_overrides={"RUNNER_BACKEND_TEST": "present"},
    )
    assert result.return_code == 0
    assert result.output.strip() == "present"


def test_watchdog_output_is_bounded_for_noisy_process(tmp_path):
    from runner.config.defaults import MAX_PROCESS_OUTPUT_CHARS
    from runner.runtime.process_runner import run_process

    code = "import sys; sys.stdout.write('A' * 250000 + 'END\\n'); sys.stdout.flush()"
    result = run_process(
        [sys.executable, "-c", code],
        tmp_path,
        10,
        idle_timeout_after_change=10,
        change_detected=lambda: False,
    )

    assert result.return_code == 0
    assert len(result.output) <= MAX_PROCESS_OUTPUT_CHARS
    assert result.output.startswith("A")
    assert result.output.endswith("END\n")
    assert "omitted" in result.output
