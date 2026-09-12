from __future__ import annotations

import shutil
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from runner.task_runner import TaskRunner
from runner import bootstrap
from runner.config.runtime import RuntimeConfig
from runner.errors import RunnerError
from runner.plugins.safety import git_subcommand
from runner.project.policy import POLICY_FILENAME, protected_paths
from runner.runtime.process_runner import run_process
from runner.plugins.safety import normalize_paths, restore_changed, snapshot


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
def test_runner_child_process_blocks_git_writes_but_allows_read_only_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap, "_current", None)
    config = RuntimeConfig(project_root=str(tmp_path), validator="ai", human_output=False)
    with bootstrap.runtime_scope(config):
        version = run_process(["git", "--version"], tmp_path, 10)
        blocked = run_process(["git", "-C", str(tmp_path), "add", "."], tmp_path, 10)

    assert version.return_code == 0
    assert "git version" in version.output.lower()
    assert blocked.return_code == 126
    assert "human review is required" in blocked.output.lower()


def test_policy_supports_always_and_project_instructions(tmp_path: Path) -> None:
    from runner.project.policy import instruction_text

    (tmp_path / POLICY_FILENAME).write_text(
        "instructions:\n"
        "  always: |\n"
        "    Never hardcode project-specific values.\n"
        "  project: |\n"
        "    Keep configuration data-driven.\n",
        encoding="utf-8",
    )

    assert instruction_text(tmp_path, "always") == "Never hardcode project-specific values."
    assert instruction_text(tmp_path, "project") == "Keep configuration data-driven."


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
    roots = normalize_paths([
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


def test_restore_changed_cleans_snapshot_if_restore_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from runner.plugins import safety

    protected = tmp_path / "locked"
    protected.mkdir()
    (protected / "keep.txt").write_text("original", encoding="utf-8")
    saved = snapshot([protected])
    backup = next(data for _hash, data in saved.values() if isinstance(data, Path))
    backup_root = backup.parent
    (protected / "keep.txt").write_text("changed", encoding="utf-8")

    def fail_restore(*_args, **_kwargs):
        raise OSError("restore failed")

    monkeypatch.setattr(safety, "restore_project_changes", fail_restore)
    with pytest.raises(OSError, match="restore failed"):
        restore_changed(saved)

    assert not backup_root.exists()


def test_safety_snapshot_and_restore_supports_deep_paths(tmp_path: Path) -> None:
    """Safety must not drop protection merely because a Windows-style path is long."""
    parent = tmp_path
    for index in range(14):
        parent = parent / f"layer_{index:02d}_abcdefghij"
    parent.mkdir(parents=True)
    protected = parent / "protected_file_with_long_name.txt"
    protected.write_text("before", encoding="utf-8")
    assert len(str(protected)) > 260

    saved = snapshot([protected])
    protected.write_text("after", encoding="utf-8")

    assert restore_changed(saved) == [str(protected)]
    assert protected.read_text(encoding="utf-8") == "before"


def test_protected_folder_ignores_common_runtime_build_and_ide_artifacts(tmp_path: Path) -> None:
    protected = tmp_path / "locked"
    protected.mkdir()
    (protected / "source.py").write_text("original", encoding="utf-8")
    saved = snapshot([protected])

    ignored_files = [
        ".git/index", ".vs/state.bin", ".vscode/settings.json", ".idea/workspace.xml",
        ".gradle/cache.bin", ".pytest_cache/state", ".mypy_cache/state",
        ".ruff_cache/state", "__pycache__/source.cpython-310.pyc", "bin/app.dll",
        "obj/app.obj", "build/output.bin", "dist/package.bin", "coverage/result.xml",
        "htmlcov/index.html", "node_modules/pkg/index.js", "target/app.jar",
        "TestResults/result.trx",
    ]
    for relative in ignored_files:
        path = protected / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("runtime", encoding="utf-8")
    (protected / ".coverage").write_text("runtime", encoding="utf-8")
    (protected / ".DS_Store").write_text("runtime", encoding="utf-8")
    (protected / "Thumbs.db").write_text("runtime", encoding="utf-8")

    assert restore_changed(saved) == []
    assert all((protected / relative).exists() for relative in ignored_files)


def test_protected_restore_preserves_ignored_artifacts_when_source_changes(tmp_path: Path) -> None:
    protected = tmp_path / "locked"
    protected.mkdir()
    source = protected / "source.py"
    source.write_text("original", encoding="utf-8")
    generated = protected / "bin" / "app.dll"
    generated.parent.mkdir()
    generated.write_text("before", encoding="utf-8")
    saved = snapshot([protected])

    source.write_text("changed", encoding="utf-8")
    generated.write_text("after", encoding="utf-8")

    assert restore_changed(saved) == [str(protected)]
    assert source.read_text(encoding="utf-8") == "original"
    assert generated.read_text(encoding="utf-8") == "after"


def test_dotfiles_are_not_blanket_ignored_by_safety(tmp_path: Path) -> None:
    protected = tmp_path / "locked"
    protected.mkdir()
    dotfile = protected / ".gitignore"
    dotfile.write_text("before\n", encoding="utf-8")
    saved = snapshot([protected])

    dotfile.write_text("after\n", encoding="utf-8")

    assert restore_changed(saved) == [str(protected)]
    assert dotfile.read_text(encoding="utf-8") == "before\n"


def test_runner_child_process_disables_python_bytecode_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap, "_current", None)
    module = tmp_path / "helper.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    config = RuntimeConfig(project_root=str(tmp_path), validator="ai", human_output=False)
    with bootstrap.runtime_scope(config):
        result = run_process(
            [
                sys.executable,
                "-c",
                "import os, helper; print(os.environ.get('PYTHONDONTWRITEBYTECODE')); print(helper.VALUE)",
            ],
            tmp_path,
            10,
        )

    assert result.return_code == 0
    assert result.output.splitlines()[-2:] == ["1", "1"]
    assert not (tmp_path / "__pycache__").exists()
