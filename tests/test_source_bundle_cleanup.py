from tool.bundle import DEFAULT_EXCLUDES, excluded


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
    assert not excluded("runner/workflow/pipeline.py", DEFAULT_EXCLUDES)
