from pathlib import Path

from runner.resources import read_text, write_text
from runner.runtime.run_state import RunState, StateStore
from runner.utils.files import copy_path, digest, remove_path
from runner.workflow.snapshot import freeze_run_resource, load_run_resource


def _deep_root(tmp_path: Path) -> Path:
    root = tmp_path
    for index in range(7):
        root = root / (f"segment-{index}-" + "x" * 38)
    root.mkdir(parents=True)
    assert len(str(root)) > 300
    return root


def test_core_runtime_io_supports_deep_project_paths(tmp_path: Path):
    root = _deep_root(tmp_path)
    source = root / "source.txt"
    write_text(source, "deep")
    assert read_text(source)[0] == "deep"

    copied = root / "nested" / "copy.txt"
    copy_path(source, copied)
    assert digest(copied) == digest(source)
    remove_path(copied)
    assert not copied.exists()

    work = root / ".ai-task-runner"
    store = StateStore(root, work)
    state = RunState(run_id="run", goal="goal", project_root=str(root))
    store.save(state)
    resumed = store.load_or_create("", resume=True, force_new=False)
    assert resumed.run_id == "run"


def test_frozen_run_resource_supports_deep_project_paths(tmp_path: Path):
    root = _deep_root(tmp_path)
    source = root / "prompt.md"
    write_text(source, "goal")
    frozen = freeze_run_resource(source, root, ".ai-task-runner", "goal")
    assert frozen is not None
    loaded = load_run_resource(root, ".ai-task-runner", "goal")
    assert loaded is not None and loaded[1] == "goal"
