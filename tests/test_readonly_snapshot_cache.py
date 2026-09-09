from pathlib import Path
from types import SimpleNamespace

from runner.plugins.safety import SafetyHook


class _SafetyHook(SafetyHook):
    def _protected(self, root: Path):
        return []


def _context(root: Path, mode: str, actor: str = "ai"):
    work = root / ".ai-task-runner"
    work.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(root=root, work=work, mode=mode, actor=actor)


def test_readonly_snapshot_is_reused_and_restores_mutation(tmp_path: Path):
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


def test_writable_stage_incrementally_updates_reused_readonly_baseline(tmp_path: Path):
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
