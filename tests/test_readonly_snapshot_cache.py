from types import SimpleNamespace
from pathlib import Path

import pytest

from runner.plugins.safety import SafetyHook


class _SafetyHook(SafetyHook):
    def _protected(self, root: Path):
        return []


def _context(root: Path, mode: str, actor: str = "ai"):
    work = root / ".ai-task-runner"
    work.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(root=root, work=work, mode=mode, actor=actor)


def _stage_context(root: Path, mode: str, readonly_safety: str, actor: str = "ai"):
    context = _context(root, mode, actor)
    context.stage = SimpleNamespace(readonly_safety=readonly_safety)
    return context


def _runtime(monkeypatch: pytest.MonkeyPatch, readonly_safety: str) -> None:
    monkeypatch.setattr(
        "runner.plugins.safety.current_runtime",
        lambda: SimpleNamespace(config=SimpleNamespace(readonly_safety=readonly_safety)),
    )


def test_readonly_snapshot_is_reused_and_restores_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _runtime(monkeypatch, "restore")
    root = tmp_path / "project"
    root.mkdir()
    target = root / "value.txt"
    target.write_text("before", encoding="utf-8")
    hook = _SafetyHook()

    first = hook.before_execution(_context(root, "readonly", "review"))
    backup = first.backup
    assert backup is not None and backup.is_dir()
    target.write_text("mutated", encoding="utf-8")
    violations = hook.after_execution(_context(root, "readonly", "review"), first)
    assert target.read_text(encoding="utf-8") == "before"
    assert violations and violations[0].kind == "readonly"

    second = hook.before_execution(_context(root, "readonly", "validator"))
    assert second.backup == backup
    hook.after_execution(_context(root, "readonly", "validator"), second)


def test_writable_stage_incrementally_updates_reused_readonly_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _runtime(monkeypatch, "restore")
    root = tmp_path / "project"
    root.mkdir()
    target = root / "value.txt"
    target.write_text("v1", encoding="utf-8")
    hook = _SafetyHook()

    token = hook.before_execution(_context(root, "readonly", "review"))
    hook.after_execution(_context(root, "readonly", "review"), token)

    write = hook.before_execution(_context(root, "write", "task"))
    target.write_text("v2", encoding="utf-8")
    assert hook.after_execution(_context(root, "write", "task"), write) == []

    readonly = hook.before_execution(_context(root, "readonly", "review"))
    target.write_text("bad", encoding="utf-8")
    hook.after_execution(_context(root, "readonly", "review"), readonly)
    assert target.read_text(encoding="utf-8") == "v2"


def test_readonly_observe_reports_without_restoring_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _runtime(monkeypatch, "observe")
    root = tmp_path / "project"
    root.mkdir()
    target = root / "value.txt"
    target.write_text("before", encoding="utf-8")
    hook = _SafetyHook()

    token = hook.before_execution(_context(root, "readonly", "review"))
    target.write_text("observed", encoding="utf-8")
    violations = hook.after_execution(_context(root, "readonly", "review"), token)

    assert target.read_text(encoding="utf-8") == "observed"
    assert violations and violations[0].kind == "readonly"
    assert "observed and not restored" in violations[0].message

    next_token = hook.before_execution(_context(root, "readonly", "review"))
    target.write_text("second", encoding="utf-8")
    hook.after_execution(_context(root, "readonly", "review"), next_token)
    assert target.read_text(encoding="utf-8") == "second"


def test_readonly_observe_still_restores_protected_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _runtime(monkeypatch, "observe")
    root = tmp_path / "project"
    root.mkdir()
    protected = root / "locked.txt"
    protected.write_text("before", encoding="utf-8")

    class ProtectedSafetyHook(SafetyHook):
        def _protected(self, root: Path):
            return [protected]

    hook = ProtectedSafetyHook()
    token = hook.before_execution(_context(root, "readonly", "review"))
    protected.write_text("bad", encoding="utf-8")
    violations = hook.after_execution(_context(root, "readonly", "review"), token)

    assert protected.read_text(encoding="utf-8") == "before"
    assert any(violation.kind == "protected" for violation in violations)


def test_stage_readonly_safety_observe_overrides_run_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _runtime(monkeypatch, "restore")
    root = tmp_path / "project"
    root.mkdir()
    target = root / "value.txt"
    target.write_text("before", encoding="utf-8")
    hook = _SafetyHook()
    context = _stage_context(root, "readonly", "observe", "review")

    token = hook.before_execution(context)
    target.write_text("stage-observed", encoding="utf-8")
    violations = hook.after_execution(context, token)

    assert target.read_text(encoding="utf-8") == "stage-observed"
    assert violations and "observed and not restored" in violations[0].message
