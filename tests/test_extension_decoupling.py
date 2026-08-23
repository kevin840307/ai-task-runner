from pathlib import Path

import pytest

from runner.config import RuntimeConfig
from runner.errors import RunnerError
from runner.runtime.execution import guarded_call, readonly_ask
from runner.runtime.extensions import bootstrap
from runner.runtime.process_control import run_process


def _config(tmp_path, **kwargs):
    return RuntimeConfig(
        goal="g",
        project_root=str(tmp_path),
        validator="ai",
        human_output=False,
        retry_delay=0,
        retry_wait=0,
        retry_max_wait=0,
        **kwargs,
    )


def test_runner_and_stages_do_not_import_concrete_safety_extensions():
    root = Path(__file__).resolve().parents[1]
    paths = [root / "runner/engine/core.py", *list((root / "runner/workflow").rglob("*.py"))]
    forbidden = ("runner.extensions.safety", "runner.safety", "GitGuard", "FileProtection", "ReadOnlyGuard")
    offenders = {
        str(path.relative_to(root)): term
        for path in paths
        for term in forbidden
        if term in path.read_text(encoding="utf-8")
    }
    assert offenders == {}


def test_protected_file_hook_restores_changes(tmp_path):
    locked = tmp_path / "locked.txt"
    locked.write_text("original", encoding="utf-8")
    bootstrap(_config(tmp_path, protect_file=[str(locked)]))

    def mutate():
        locked.write_text("changed", encoding="utf-8")

    with pytest.raises(RunnerError):
        guarded_call(mutate, tmp_path, tmp_path / ".ai-task-runner", actor="test")
    assert locked.read_text(encoding="utf-8") == "original"


def test_readonly_hook_restores_project_changes(tmp_path):
    target = tmp_path / "data.txt"
    target.write_text("before", encoding="utf-8")
    bootstrap(_config(tmp_path))

    class Agent:
        def ask(self, *args, **kwargs):
            target.write_text("after", encoding="utf-8")
            return "ok"

    with pytest.raises(RunnerError):
        readonly_ask(Agent(), "read", tmp_path, tmp_path / ".ai-task-runner")
    assert target.read_text(encoding="utf-8") == "before"


def test_git_guard_is_loaded_by_extension_bootstrap(tmp_path):
    bootstrap(_config(tmp_path))
    result = run_process(["git", "-C", str(tmp_path), "add", "."], tmp_path, 10)
    assert result.return_code == 126
    assert "blocked" in result.output.lower()
