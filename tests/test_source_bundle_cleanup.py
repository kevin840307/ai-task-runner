from pathlib import Path

from tool.bundle import DEFAULT_EXCLUDES, excluded

ROOT = Path(__file__).resolve().parents[1]


def test_default_bundle_excludes_runtime_and_cache_artifacts():
    excluded_paths = [
        ".pytest_cache/v/cache/nodeids",
        "runner/__pycache__/x.cpython-313.pyc",
        "examples/demo/.ai-task-runner/state.json",
        "examples/demo/.ai-task-runner/validator-reports/file/summary.txt",
        "examples/demo/validator-reports/file/summary.txt",
        "tests/x.pyc",
    ]
    assert all(excluded(path, DEFAULT_EXCLUDES) for path in excluded_paths)


def test_bundle_includes_current_core_and_deleted_compat_modules_stay_absent():
    assert not excluded("runner/workflow/flow_engine.py", DEFAULT_EXCLUDES)
    for path in (
        "runner/task_runner.py",
        "runner/workflow/pipeline.py",
        "runner/workflow/linear_routing.py",
        "runner/workflow/semantic_routing.py",
    ):
        assert not (ROOT / path).exists()
