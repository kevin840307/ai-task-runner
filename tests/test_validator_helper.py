from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from runner.config.project_policy import protected_paths


def test_runner_validator_execution_has_no_helper_filename_policy():
    source = Path("runner/flow/stages/python_validation.py").read_text(encoding="utf-8")
    core = Path("runner/task_runner.py").read_text(encoding="utf-8")
    assert "VALIDATOR_HELPER" not in source + core
    assert "prepare_validator_helper" not in source + core
    assert "ai_task_runner_validator.py" not in source + core


def test_policy_can_protect_example_owned_validator_helper(tmp_path):
    (tmp_path / ".ai-task-runner.yaml").write_text(
        "protected_paths:\n  - validation.py\n  - ai_task_runner_validator.py\n",
        encoding="utf-8",
    )
    paths = protected_paths(tmp_path)
    assert (tmp_path / "ai_task_runner_validator.py").resolve() in paths


def test_example_validator_falls_back_to_local_helper_without_installed_package(tmp_path):
    project = Path("examples/01_basic_python_validator/project").resolve()
    # -S excludes site-packages, so the example must rely on its own local helper.
    result = subprocess.run(
        [sys.executable, "-S", str(project / "validation.py"), "--project-root", str(project)],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=20,
    )
    # The starter project may fail functional validation, but helper import itself must succeed.
    assert "ModuleNotFoundError" not in result.stderr
    assert "ai_task_runner_validator" not in result.stderr
