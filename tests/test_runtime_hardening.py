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

    result = run_process([sys.executable, "-c", code], tmp_path, 1)

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
