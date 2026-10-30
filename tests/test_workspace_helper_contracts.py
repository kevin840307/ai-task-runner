from __future__ import annotations

from pathlib import Path

from runner.workspace import (
    RUNNER_RULE_MARKER,
    PROJECT_INSTRUCTIONS_START,
    changed_project_files,
    ensure_instruction_file,
    excluded_dirs,
    is_malformed_windows_path_filename,
    is_technical_artifact,
    normalize_project_name,
    project_manifest,
    restore_project_changes,
    tree_manifest,
)


def test_technical_artifact_and_excluded_directory_contract(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    work = root / ".runner-work"

    assert is_technical_artifact(".git", is_dir=True)
    assert is_technical_artifact("node_modules/pkg.js")
    assert is_technical_artifact("cache.pyc", is_dir=False)
    assert is_technical_artifact("src/app.py", is_dir=False) is False
    assert is_technical_artifact(Path()) is False

    excluded = excluded_dirs(root, work)
    assert ".git" in excluded
    assert "node_modules" in excluded
    assert ".runner-work" in excluded

    external = excluded_dirs(root, tmp_path / "external-work")
    assert ".runner-work" not in external


def test_tree_and_project_manifest_exclude_runtime_and_technical_artifacts(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    work = root / ".runner-work"
    work.mkdir()
    (work / "state.json").write_text("runtime", encoding="utf-8")

    src = root / "src"
    src.mkdir()
    (src / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "README.md").write_text("readme\n", encoding="utf-8")

    node_modules = root / "node_modules"
    node_modules.mkdir()
    (node_modules / "pkg.js").write_text("ignored", encoding="utf-8")
    (root / ".coverage").write_text("ignored", encoding="utf-8")
    (root / "cache.pyc").write_bytes(b"ignored")

    direct = tree_manifest(root, excluded_dirs(root, work))
    via_project = project_manifest(root, work)

    assert direct == via_project
    assert direct["src"][0] == "dir"
    assert direct["src/app.py"][0] == "file"
    assert direct["README.md"][0] == "file"
    assert ".runner-work" not in direct
    assert "node_modules" not in direct
    assert ".coverage" not in direct
    assert "cache.pyc" not in direct


def test_changed_project_files_reports_file_delta_but_not_directory_delta(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    work = root / ".work"
    work.mkdir()

    (root / "keep.txt").write_text("before\n", encoding="utf-8")
    (root / "delete.txt").write_text("delete me\n", encoding="utf-8")
    before = project_manifest(root, work)

    (root / "keep.txt").write_text("after\n", encoding="utf-8")
    (root / "delete.txt").unlink()
    nested = root / "newdir"
    nested.mkdir()
    (nested / "new.txt").write_text("new\n", encoding="utf-8")
    (work / "state.json").write_text("ignored runtime change", encoding="utf-8")

    assert changed_project_files(root, work, before) == [
        "delete.txt",
        "keep.txt",
        "newdir/new.txt",
    ]


def test_restore_project_changes_removes_new_files_and_restores_backup(tmp_path):
    root = tmp_path / "project"
    backup = tmp_path / "backup"
    root.mkdir()
    backup.mkdir()

    (backup / "existing.txt").write_text("original\n", encoding="utf-8")
    nested_backup = backup / "nested"
    nested_backup.mkdir()
    (nested_backup / "value.txt").write_text("nested-original\n", encoding="utf-8")

    (root / "existing.txt").write_text("changed\n", encoding="utf-8")
    (root / "new.txt").write_text("new\n", encoding="utf-8")
    nested_root = root / "nested"
    nested_root.mkdir()
    (nested_root / "value.txt").write_text("nested-changed\n", encoding="utf-8")

    restore_project_changes(
        root,
        backup,
        ["existing.txt", "new.txt", "nested/value.txt"],
    )

    assert (root / "existing.txt").read_text(encoding="utf-8") == "original\n"
    assert not (root / "new.txt").exists()
    assert (root / "nested" / "value.txt").read_text(encoding="utf-8") == "nested-original\n"


def test_malformed_windows_path_filename_detection_is_narrow():
    assert is_malformed_windows_path_filename("C\uf03aUsersKevinprojectfile.txt")
    assert is_malformed_windows_path_filename("d\uf03aworkoutput.json")
    assert not is_malformed_windows_path_filename("C:/Users/Kevin/project/file.txt")
    assert not is_malformed_windows_path_filename("normal-file.txt")
    assert not is_malformed_windows_path_filename("C.txt")


def test_ensure_instruction_file_adds_runner_rules_project_block_and_is_idempotent(
    tmp_path,
):
    root = tmp_path / "project"
    root.mkdir()
    (root / ".ai-task-runner.yaml").write_text(
        "instructions:\n"
        "  project: |\n"
        "    Keep public API compatibility.\n",
        encoding="utf-8",
    )

    path = ensure_instruction_file(root, "AGENTS.md")
    first = path.read_text(encoding="utf-8")

    assert RUNNER_RULE_MARKER in first
    assert PROJECT_INSTRUCTIONS_START in first
    assert "Keep public API compatibility." in first
    assert "use a project-relative path" in first

    ensure_instruction_file(root, "AGENTS.md")
    second = path.read_text(encoding="utf-8")
    assert second.count(RUNNER_RULE_MARKER) == 1
    assert second.count(PROJECT_INSTRUCTIONS_START) == 1


def test_normalize_project_name_collapses_whitespace_and_enforces_limit():
    assert normalize_project_name("  My   Project\nName ") == "My Project Name"
    assert normalize_project_name("") == ""

    import pytest

    with pytest.raises(ValueError, match="project_name is too long"):
        normalize_project_name("x" * 121)
