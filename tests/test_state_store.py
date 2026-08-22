import json

import pytest

from runner.defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS
from runner.errors import RunnerError
from runner.models import RunState, Task
from runner.state_store import StateStore


def _store(tmp_path, monkeypatch) -> StateStore:
    from runner import state_store

    monkeypatch.setattr(
        state_store.tempfile,
        "gettempdir",
        lambda: str(tmp_path / "external-temp"),
    )
    return StateStore(tmp_path.resolve(), tmp_path / ".ai-task-runner")


def test_state_store_saves_primary_and_external_backup(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    state = store.load_or_create("goal", resume=False, force_new=False)

    store.save(state)

    primary = json.loads(store.path.read_text(encoding="utf-8"))
    backup = json.loads(store.backup_path.read_text(encoding="utf-8"))
    assert primary == backup == state.dump()


def test_state_store_restores_backup_and_bounds_resume_output(
    tmp_path,
    monkeypatch,
):
    store = _store(tmp_path, monkeypatch)
    state = RunState(
        run_id="run-1",
        goal="goal",
        project_root=str(tmp_path.resolve()),
        validator_output="V" * (MAX_VALIDATOR_OUTPUT_CHARS + 100),
        tasks=[
            Task(
                id="t1",
                title="title",
                description="description",
                last_output="T" * (MAX_TASK_OUTPUT_CHARS + 100),
            )
        ],
    )
    store.save(state)
    store.path.write_text("{broken", encoding="utf-8")

    resumed = store.load_or_create("", resume=True, force_new=False)

    assert resumed.run_id == "run-1"
    assert len(resumed.validator_output) <= MAX_VALIDATOR_OUTPUT_CHARS
    assert len(resumed.tasks[0].last_output) == MAX_TASK_OUTPUT_CHARS


def test_state_store_reports_missing_resume_state(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)

    with pytest.raises(RunnerError, match="resume state not found"):
        store.load_or_create("", resume=True, force_new=False)
