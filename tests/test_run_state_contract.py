import json
from pathlib import Path

import pytest

import runner.runtime.run_state as run_state
from runner.config.defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS
from runner.errors import ConfigurationError, RunnerError
from runner.runtime.run_state import RunState, StateStore, Task, normalize_state, set_stage


def _task(**overrides):
    values = {
        "id": "task-1",
        "title": "Task",
        "description": "Do the work",
    }
    values.update(overrides)
    return Task(**values)


def _state(tmp_path: Path, **overrides):
    values = {
        "run_id": "run-1",
        "goal": "Goal",
        "project_root": str(tmp_path),
        "tasks": [_task()],
    }
    values.update(overrides)
    return RunState(**values)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("id", "", "tasks[1].id"),
        ("title", " ", "tasks[1].title"),
        ("description", 1, "tasks[1].description"),
        ("acceptance_criteria", ["ok", ""], "acceptance_criteria"),
        ("status", "running", "status is invalid"),
        ("attempts", -1, "attempts must be non-negative"),
        ("changed_files", ["ok.py", ""], "changed_files must be strings"),
    ],
)
def test_task_validation_rejects_invalid_durable_fields(field, value, message):
    task = _task(**{field: value})
    with pytest.raises(ValueError, match=message.replace("[", r"\[").replace("]", r"\]")):
        task.validate(1)


def test_run_state_validation_accepts_full_durable_shape(tmp_path):
    state = _state(
        tmp_path,
        validator_output="validator",
        ai_session_id="main-session",
        stage="execute",
        stage_started_at=1.5,
        last_activity_at=2.5,
        workflow_position=1,
        expanded_workflow=[{"name": "execute", "type": "base"}],
        dynamic_groups={"producer": "group-1"},
        dynamic_task_groups={"group-1": ["task-1"]},
        expansion_counter=2,
        workflow_fingerprint="fingerprint",
        transition_previous={"execute": {"status": "pass"}},
        transition_history=[{"stage": "execute", "status": "pass"}],
        stage_sessions={"execute": "role-session"},
        review_failures={"review": 1},
    )

    state.validate()
    dumped = state.dump()

    assert dumped["tasks"][0]["id"] == "task-1"
    assert dumped["stage_sessions"] == {"execute": "role-session"}
    assert dumped["review_failures"] == {"review": 1}


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda s: setattr(s, "run_id", ""), "state.run_id"),
        (lambda s: setattr(s, "cycle", 0), "cycle must be positive"),
        (lambda s: setattr(s, "current", 2), "current is outside"),
        (lambda s: setattr(s, "completed", "yes"), "completed must be boolean"),
        (lambda s: setattr(s, "stage_started_at", -1), "stage_started_at"),
        (lambda s: setattr(s, "transition_previous", []), "transition_previous"),
        (lambda s: setattr(s, "transition_history", ["bad"]), "transition_history"),
        (lambda s: setattr(s, "expanded_workflow", ["bad"]), "expanded_workflow"),
        (lambda s: setattr(s, "dynamic_groups", {"": "x"}), "dynamic_groups"),
        (lambda s: setattr(s, "dynamic_task_groups", {"g": [""]}), "dynamic_task_groups.g"),
        (lambda s: setattr(s, "stage_sessions", {"": "x"}), "stage_sessions keys"),
        (lambda s: setattr(s, "stage_sessions", {"stage": 1}), "stage_sessions.stage"),
        (lambda s: setattr(s, "review_failures", {"review": -1}), "review_failures.review"),
        (lambda s: setattr(s, "completed", True), "completed state contains pending tasks"),
    ],
)
def test_run_state_validation_rejects_invalid_shapes(tmp_path, mutator, message):
    state = _state(tmp_path)
    mutator(state)
    with pytest.raises(ValueError, match=message):
        state.validate()


def test_run_state_load_rejects_removed_state_and_task_fields(tmp_path):
    base = _state(tmp_path).dump()

    with pytest.raises(ValueError, match="removed fields: obsolete"):
        RunState.load({**base, "obsolete": True})

    with pytest.raises(ValueError, match=r"tasks\[1\] contains removed fields: obsolete"):
        RunState.load({
            **base,
            "tasks": [{**base["tasks"][0], "obsolete": True}],
        })

    with pytest.raises(ValueError, match="state.tasks must be an array"):
        RunState.load({**base, "tasks": {}})
    with pytest.raises(ValueError, match=r"tasks\[1\] must be an object"):
        RunState.load({**base, "tasks": ["bad"]})


def test_state_store_create_requires_goal_and_existing_state_policy(tmp_path):
    work = tmp_path / ".work"
    store = StateStore(tmp_path, work)

    created = store.load_or_create("Goal", resume=False, force_new=False)
    assert created.goal == "Goal"
    assert created.project_root == str(tmp_path)
    assert created.run_id

    with pytest.raises(RunnerError, match="--goal is required"):
        store.load_or_create("", resume=False, force_new=False)

    work.mkdir()
    store.path.write_text("{}", encoding="utf-8")
    with pytest.raises(RunnerError, match="state exists"):
        store.load_or_create("Goal", resume=False, force_new=False)

    forced = store.load_or_create("New Goal", resume=False, force_new=True)
    assert forced.goal == "New Goal"


def test_state_store_save_and_resume_roundtrip_bounds_large_outputs(tmp_path):
    store = StateStore(tmp_path, tmp_path / ".work")
    state = _state(
        tmp_path,
        validator_output="V" * (MAX_VALIDATOR_OUTPUT_CHARS + 100),
    )
    state.tasks[0].last_output = "T" * (MAX_TASK_OUTPUT_CHARS + 100)

    store.save(state)

    resumed = store.load_or_create("", resume=True, force_new=False)
    assert resumed.run_id == state.run_id
    assert len(resumed.validator_output) <= MAX_VALIDATOR_OUTPUT_CHARS
    assert len(resumed.tasks[0].last_output) == MAX_TASK_OUTPUT_CHARS
    assert resumed.tasks[0].last_output == "T" * MAX_TASK_OUTPUT_CHARS
    assert store.backup_path.is_file()


def test_state_store_resume_restores_valid_backup_after_primary_corruption(tmp_path):
    store = StateStore(tmp_path, tmp_path / ".work")
    state = _state(tmp_path)
    store.save(state)
    store.path.write_text("{corrupt", encoding="utf-8")

    resumed = store.load_or_create("", resume=True, force_new=False)

    assert resumed.run_id == state.run_id
    assert json.loads(store.path.read_text(encoding="utf-8"))["run_id"] == state.run_id


def test_state_store_resume_rejects_missing_or_foreign_project_state(tmp_path):
    store = StateStore(tmp_path, tmp_path / ".work")

    with pytest.raises(ConfigurationError, match="resume state not found"):
        store.load_or_create("", resume=True, force_new=False)

    foreign = _state(tmp_path / "other")
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps(foreign.dump()), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="different project_root"):
        store.load_or_create("", resume=True, force_new=False)


def test_restore_backup_rejects_missing_invalid_and_foreign_backup(tmp_path):
    store = StateStore(tmp_path, tmp_path / ".work")
    store.backup_path.unlink(missing_ok=True)
    assert store.restore_backup() is False

    store.backup_path.parent.mkdir(parents=True, exist_ok=True)
    store.backup_path.write_text("{bad", encoding="utf-8")
    assert store.restore_backup() is False

    foreign = _state(tmp_path / "other")
    store.backup_path.write_text(json.dumps(foreign.dump()), encoding="utf-8")
    assert store.restore_backup() is False


def test_state_store_backup_failure_is_logged_but_primary_remains_authoritative(
    tmp_path, monkeypatch
):
    store = StateStore(tmp_path, tmp_path / ".work")
    state = _state(tmp_path)
    original = run_state._write_json

    def fail_backup(path, data):
        if path == store.backup_path:
            raise OSError("backup unavailable")
        return original(path, data)

    monkeypatch.setattr(run_state, "_write_json", fail_backup)
    monkeypatch.setattr(run_state, "touch_heartbeat", lambda: None)

    store.save(state)

    assert store.path.is_file()
    assert RunState.load(json.loads(store.path.read_text(encoding="utf-8"))).run_id == "run-1"
    warning = store.work / "state-backup-warning.log"
    assert warning.is_file()
    assert "backup unavailable" in warning.read_text(encoding="utf-8")


def test_set_stage_tracks_stage_start_activity_and_bounded_error(tmp_path):
    state = _state(tmp_path)

    set_stage(state, "execute", "x" * 1200, now=10)
    assert state.stage == "execute"
    assert state.stage_started_at == 10
    assert state.last_activity_at == 10
    assert state.last_error == "x" * 1000

    set_stage(state, "execute", "", now=20)
    assert state.stage_started_at == 10
    assert state.last_activity_at == 20
    assert state.last_error == ""

    set_stage(state, "review", now=30)
    assert state.stage == "review"
    assert state.stage_started_at == 30


def test_normalize_state_repairs_completion_current_and_completed_cursor(tmp_path):
    state = _state(tmp_path, completed=True, stage="execute")
    assert normalize_state(state) is True
    assert state.completed is False

    state.current = 9
    assert normalize_state(state) is True
    assert state.current == len(state.tasks)

    state.tasks = [
        _task(id="a", status="completed"),
        _task(id="b", status="pending"),
        _task(id="c", status="completed"),
    ]
    state.current = 0
    assert normalize_state(state) is True
    assert state.current == 1

    assert normalize_state(state) is False
