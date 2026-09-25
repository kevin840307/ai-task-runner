from __future__ import annotations

import json
import sys
from pathlib import Path

from runner.config.defaults import MAX_PROCESS_OUTPUT_CHARS
from runner.runtime.process_runner import run_process
from runner.runtime.run_state import RunState, StateStore, _write_json
from runner.utils.files import atomic_write_text


def _state(root: Path, *, cycle: int, stage: str) -> RunState:
    return RunState(
        run_id=f"run-{cycle}",
        goal="goal",
        project_root=str(root.resolve()),
        cycle=cycle,
        stage=stage,
    )


def test_resume_prefers_valid_primary_over_stale_backup(tmp_path):
    work = tmp_path / ".run"
    store = StateStore(tmp_path.resolve(), work)
    primary = _state(tmp_path, cycle=2, stage="new")
    stale = _state(tmp_path, cycle=1, stage="old")
    _write_json(store.path, primary.dump())
    _write_json(store.backup_path, stale.dump())

    resumed = store.load_or_create("", resume=True, force_new=False)

    assert resumed.cycle == 2
    assert resumed.stage == "new"
    assert json.loads(store.backup_path.read_text(encoding="utf-8"))["cycle"] == 1


def test_resume_restores_backup_when_primary_is_invalid(tmp_path):
    work = tmp_path / ".run"
    work.mkdir()
    store = StateStore(tmp_path.resolve(), work)
    store.path.write_text("{invalid", encoding="utf-8")
    backup = _state(tmp_path, cycle=3, stage="backup")
    _write_json(store.backup_path, backup.dump())

    resumed = store.load_or_create("", resume=True, force_new=False)

    assert resumed.cycle == 3
    assert resumed.stage == "backup"
    assert json.loads(store.path.read_text(encoding="utf-8"))["cycle"] == 3


def test_resume_restores_backup_when_primary_is_missing(tmp_path):
    store = StateStore(tmp_path.resolve(), tmp_path / ".run")
    backup = _state(tmp_path, cycle=4, stage="backup")
    _write_json(store.backup_path, backup.dump())

    resumed = store.load_or_create("", resume=True, force_new=False)

    assert resumed.cycle == 4
    assert resumed.stage == "backup"


def test_normal_process_output_is_bounded(tmp_path):
    code = "import sys; sys.stdout.write('A' * 250000 + 'END\\n'); sys.stdout.flush()"

    result = run_process([sys.executable, "-c", code], tmp_path, 10)

    assert result.return_code == 0
    assert len(result.output) <= MAX_PROCESS_OUTPUT_CHARS
    assert result.output.startswith("A")
    assert result.output.endswith("END\n")
    assert "omitted" in result.output


def test_normal_process_timeout_keeps_bounded_partial_output(tmp_path):
    code = (
        "import sys,time; "
        "sys.stdout.write('A' * 250000 + 'TAIL\\n'); sys.stdout.flush(); "
        "time.sleep(10)"
    )

    result = run_process([sys.executable, "-c", code], tmp_path, 3)

    assert result.timed_out is True
    assert result.idle_timed_out is False
    assert len(result.output) <= MAX_PROCESS_OUTPUT_CHARS
    assert "omitted" in result.output
    assert result.output.endswith("TAIL\n")


def test_atomic_write_text_replaces_existing_file(tmp_path):
    path = tmp_path / "snapshot.txt"
    path.write_text("old", encoding="utf-8")

    atomic_write_text(path, "new")

    assert path.read_text(encoding="utf-8") == "new"
    assert not path.with_suffix(".txt.tmp").exists()


def test_large_normal_process_keeps_final_tail(tmp_path):
    code = "import sys; sys.stdout.write('A' * 2000000 + 'FINAL_TAIL\\n'); sys.stdout.flush()"

    result = run_process([sys.executable, "-c", code], tmp_path, 10)

    assert result.return_code == 0
    assert len(result.output) <= MAX_PROCESS_OUTPUT_CHARS
    assert result.output.endswith("FINAL_TAIL\n")
    assert "omitted" in result.output


def test_atomic_write_text_is_best_effort(tmp_path, monkeypatch):
    import runner.utils.files as files_module

    path = tmp_path / "snapshot.txt"
    temporary = path.with_suffix(".txt.tmp")
    monkeypatch.setattr(files_module.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("locked")))

    atomic_write_text(path, "new")

    assert not temporary.exists()


def test_history_observer_uses_shared_atomic_writer(tmp_path):
    from runner.plugins.history import HistoryObserver

    observer = HistoryObserver()
    debug_dir = tmp_path / "debug"
    observer({"type": "model.prompt", "debug_dir": str(debug_dir), "call_id": "c1", "text": "prompt"})
    observer({"type": "model.result", "debug_dir": str(debug_dir), "call_id": "c1", "text": "result"})

    assert (debug_dir / "history" / "c1-prompt.txt").read_text(encoding="utf-8") == "prompt"
    assert (debug_dir / "history" / "c1-result.txt").read_text(encoding="utf-8") == "result"


def test_observability_model_snapshot_uses_shared_atomic_writer(tmp_path):
    from types import SimpleNamespace
    from runner.plugins.observability import ObservabilityObserver

    observer = ObservabilityObserver(SimpleNamespace(
        config=SimpleNamespace(event_callback=None, json_events=False, script=True),
        work=tmp_path,
    ))
    debug_dir = tmp_path / "debug"
    observer({"type": "model.prompt", "debug_dir": str(debug_dir), "text": "prompt"})
    observer({"type": "model.result", "debug_dir": str(debug_dir), "text": "result"})

    assert (debug_dir / "current-prompt.txt").read_text(encoding="utf-8") == "prompt"
    assert (debug_dir / "last-prompt.txt").read_text(encoding="utf-8") == "prompt"
    assert (debug_dir / "last-result.txt").read_text(encoding="utf-8") == "result"


def test_run_state_roundtrip_preserves_bounded_recovery_attempt():
    from runner.runtime.run_state import RunState
    state = RunState(run_id="r", goal="g", project_root=".")
    state.recovery_attempt_key = "workflow:2"
    state.recovery_attempt_count = 2
    state.recovery_attempt_previous = {"stage": "grill", "data": {"missing_items": ["A"]}}
    loaded = RunState.load(state.dump())
    assert loaded.recovery_attempt_key == "workflow:2"
    assert loaded.recovery_attempt_count == 2
    assert loaded.recovery_attempt_previous == state.recovery_attempt_previous


def test_terminate_process_tree_waits_again_after_force_kill(monkeypatch):
    import os
    import subprocess
    from runner.runtime import process_runner as process_module

    class StubbornProcess:
        pid = 4242

        def __init__(self):
            self.wait_calls = []
            self.killed = False

        def poll(self):
            return None

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            if len(self.wait_calls) == 1:
                raise subprocess.TimeoutExpired("worker", timeout)
            return 0

        def kill(self):
            self.killed = True

    process = StubbornProcess()
    if os.name == "nt":
        monkeypatch.setattr(process_module.subprocess, "run", lambda *args, **kwargs: None)
    else:
        monkeypatch.setattr(process_module.os, "killpg", lambda *args, **kwargs: None)

    process_module.terminate_process_tree(process)

    assert process.killed is True
    assert process.wait_calls == [
        process_module.TERMINATION_GRACE_SECONDS,
        process_module.TERMINATION_GRACE_SECONDS,
    ]


def test_state_commit_refreshes_worker_heartbeat(tmp_path, monkeypatch):
    import os
    import time
    from runner.runtime.heartbeat import HEARTBEAT_ENV

    heartbeat = tmp_path / "heartbeat"
    heartbeat.write_text("", encoding="utf-8")
    old = time.time() - 120
    os.utime(heartbeat, (old, old))
    monkeypatch.setenv(HEARTBEAT_ENV, str(heartbeat))

    store = StateStore(tmp_path.resolve(), tmp_path / ".run")
    store.save(_state(tmp_path, cycle=1, stage="executing"))

    assert heartbeat.stat().st_mtime > old


def test_child_output_refreshes_worker_heartbeat(tmp_path, monkeypatch):
    import os
    import time
    from runner.runtime.heartbeat import HEARTBEAT_ENV

    heartbeat = tmp_path / "heartbeat"
    heartbeat.write_text("", encoding="utf-8")
    old = time.time() - 120
    os.utime(heartbeat, (old, old))
    monkeypatch.setenv(HEARTBEAT_ENV, str(heartbeat))

    result = run_process(
        [sys.executable, "-c", "print('progress', flush=True)"],
        tmp_path,
        10,
    )

    assert result.return_code == 0
    assert heartbeat.stat().st_mtime > old


def test_project_changes_refresh_worker_heartbeat_without_cli_output(tmp_path, monkeypatch):
    import os
    import time
    from runner.runtime.heartbeat import HEARTBEAT_ENV

    heartbeat = tmp_path / "heartbeat"
    heartbeat.write_text("", encoding="utf-8")
    old = time.time() - 120
    os.utime(heartbeat, (old, old))
    monkeypatch.setenv(HEARTBEAT_ENV, str(heartbeat))

    result = run_process(
        [sys.executable, "-c", "import time; time.sleep(0.2)"],
        tmp_path,
        5,
        idle_timeout_after_change=1,
        change_detected=lambda: True,
    )

    assert result.return_code == 0
    assert heartbeat.stat().st_mtime > old


def test_silent_managed_subprocess_refreshes_worker_heartbeat(tmp_path, monkeypatch):
    import os
    import time
    from runner.runtime.heartbeat import HEARTBEAT_ENV

    heartbeat = tmp_path / "heartbeat"
    heartbeat.write_text("", encoding="utf-8")
    old = time.time() - 120
    os.utime(heartbeat, (old, old))
    monkeypatch.setenv(HEARTBEAT_ENV, str(heartbeat))

    result = run_process(
        [sys.executable, "-c", "import time; time.sleep(0.2)"],
        tmp_path,
        5,
    )

    assert result.return_code == 0
    assert heartbeat.stat().st_mtime > old


def test_state_backup_failure_is_logged_without_failing_primary_commit(tmp_path, monkeypatch):
    import runner.runtime.run_state as run_state_module

    store = StateStore(tmp_path.resolve(), tmp_path / ".run")
    state = _state(tmp_path, cycle=7, stage="executing")
    original_write = run_state_module._write_json

    def fail_backup(path, data):
        if path == store.backup_path:
            raise PermissionError("backup locked")
        return original_write(path, data)

    monkeypatch.setattr(run_state_module, "_write_json", fail_backup)

    store.save(state)

    assert json.loads(store.path.read_text(encoding="utf-8"))["cycle"] == 7
    warning = (store.work / "state-backup-warning.log").read_text(encoding="utf-8")
    assert "WARNING state backup failed" in warning
    assert "primary state remains authoritative" in warning
    assert "PermissionError: backup locked" in warning
