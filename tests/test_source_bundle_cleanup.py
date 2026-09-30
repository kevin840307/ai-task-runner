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
    # Source and test code must remain in the portable project snapshot.
    included_source_paths = [
        "runner/workflow/pipeline.py",
        "tests/test_ui.py",
        "ui/tests/test_static_contract.py",
        "smoke/qwen_simple/project/README.md",
        "examples/01_basic_command_validator/project/validation.py",
    ]
    assert not any(excluded(path, DEFAULT_EXCLUDES) for path in included_source_paths)
