from __future__ import annotations

import shutil
from types import SimpleNamespace
from pathlib import Path

import pytest

from runner.engine.core import TaskRunner
from runner.errors import RunnerError
from runner.safety.git_guard import git_subcommand
from runner.safety.policy import POLICY_FILENAME, protected_paths
from runner.runtime.process_control import run_process
from runner.safety.project_guard import normalize_protected_paths, restore_changed, snapshot


def test_policy_protects_file_folder_and_policy_itself(tmp_path: Path) -> None:
    (tmp_path / POLICY_FILENAME).write_text(
        "protected_paths:\n  - ans/\n  - validation.py\n",
        encoding="utf-8",
    )
    paths = protected_paths(tmp_path)

    assert paths == [
        (tmp_path / POLICY_FILENAME).resolve(),
        (tmp_path / "ans").resolve(),
        (tmp_path / "validation.py").resolve(),
    ]




def test_runner_merges_yaml_paths_into_existing_protection(tmp_path: Path) -> None:
    (tmp_path / POLICY_FILENAME).write_text(
        "protected_paths:\n  - locked/\n",
        encoding="utf-8",
    )
    runner = TaskRunner.__new__(TaskRunner)
    runner.root = tmp_path.resolve()
    runner.args = SimpleNamespace(goal_file=None, protect_file=[])
    runner.validator = None
    runner.state_file = tmp_path / ".ai-task-runner" / "state.json"
    runner.backend_files = []

    protected = runner._build_protected_files()

    assert (tmp_path / POLICY_FILENAME).resolve() in protected
    assert (tmp_path / "locked").resolve() in protected


def test_runner_protects_ai_validator_prompt_file(tmp_path: Path) -> None:
    prompt = tmp_path / "ai_validation.md"
    prompt.write_text("check", encoding="utf-8")
    runner = TaskRunner.__new__(TaskRunner)
    runner.root = tmp_path.resolve()
    runner.args = SimpleNamespace(
        goal_file=None, ai_validator_prompt_file=str(prompt), protect_file=[]
    )
    runner.validator = None
    runner.state_file = tmp_path / ".ai-task-runner" / "state.json"
    runner.backend_files = []

    assert prompt.resolve() in runner._build_protected_files()


def test_policy_folder_snapshot_restores_modify_create_and_delete(tmp_path: Path) -> None:
    protected = tmp_path / "locked"
    protected.mkdir()
    (protected / "keep.txt").write_text("original", encoding="utf-8")
    (tmp_path / POLICY_FILENAME).write_text(
        "protected_paths:\n  - locked/\n",
        encoding="utf-8",
    )
    saved = snapshot(protected_paths(tmp_path))

    (protected / "keep.txt").write_text("changed", encoding="utf-8")
    (protected / "new.txt").write_text("new", encoding="utf-8")
    changed = restore_changed(saved)

    assert str(protected.resolve()) in changed
    assert (protected / "keep.txt").read_text(encoding="utf-8") == "original"
    assert not (protected / "new.txt").exists()



def test_policy_rejects_unknown_keys_instead_of_silently_disabling_protection(tmp_path: Path) -> None:
    (tmp_path / POLICY_FILENAME).write_text(
        "protect_paths:\n  - locked/\n",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="unknown keys"):
        protected_paths(tmp_path)


def test_policy_rejects_paths_outside_project(tmp_path: Path) -> None:
    (tmp_path / POLICY_FILENAME).write_text(
        "protected_paths:\n  - ../outside\n",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="must stay inside project_root"):
        protected_paths(tmp_path)


def test_git_subcommand_handles_global_options() -> None:
    assert git_subcommand(["status"]) == "status"
    assert git_subcommand(["-C", "repo", "add", "."]) == "add"
    assert git_subcommand(["-c", "user.name=x", "commit", "-m", "x"]) == "commit"
    assert git_subcommand(["--no-pager", "push"]) == "push"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_runner_child_process_blocks_git_writes_but_allows_read_only_git(tmp_path: Path) -> None:
    version = run_process(["git", "--version"], tmp_path, 10)
    blocked = run_process(["git", "-C", str(tmp_path), "add", "."], tmp_path, 10)

    assert version.return_code == 0
    assert "git version" in version.output.lower()
    assert blocked.return_code == 126
    assert "human review is required" in blocked.output.lower()


def test_policy_supports_always_and_project_instructions(tmp_path: Path) -> None:
    from runner.safety.policy import instructions

    (tmp_path / POLICY_FILENAME).write_text(
        "instructions:\n"
        "  always: |\n"
        "    Never hardcode project-specific values.\n"
        "  project: |\n"
        "    Keep configuration data-driven.\n",
        encoding="utf-8",
    )

    assert instructions(tmp_path, "always") == "Never hardcode project-specific values."
    assert instructions(tmp_path, "project") == "Keep configuration data-driven."


def test_policy_rejects_unknown_instruction_keys(tmp_path: Path) -> None:
    (tmp_path / POLICY_FILENAME).write_text(
        "instructions:\n  every_time: x\n",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="unknown instruction keys"):
        protected_paths(tmp_path)


def test_policy_rejects_non_string_instructions(tmp_path: Path) -> None:
    (tmp_path / POLICY_FILENAME).write_text(
        "instructions:\n  always:\n    - x\n",
        encoding="utf-8",
    )
    with pytest.raises(RunnerError, match="instruction values must be strings"):
        protected_paths(tmp_path)


def test_protected_roots_drop_descendants_without_guessing_siblings(tmp_path: Path) -> None:
    locked = (tmp_path / "locked").resolve()
    other = (tmp_path / "other.txt").resolve()
    roots = normalize_protected_paths([
        locked / "a.txt",
        other,
        locked,
        locked / "nested" / "b.txt",
    ])

    assert locked in roots
    assert other in roots
    assert locked / "a.txt" not in roots
    assert locked / "nested" / "b.txt" not in roots
    assert tmp_path.resolve() not in roots


def test_all_smoke_and_example_project_roots_have_valid_self_protecting_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    project_roots = sorted(
        path for group in (root / "examples", root / "smoke")
        for path in group.glob("*/project") if path.is_dir()
    )
    assert project_roots
    for project in project_roots:
        policy = project / POLICY_FILENAME
        assert policy.is_file(), f"missing project policy: {project}"
        paths = protected_paths(project)
        assert policy.resolve() in paths
        for path in paths:
            assert path == project.resolve() or path.is_relative_to(project.resolve())
