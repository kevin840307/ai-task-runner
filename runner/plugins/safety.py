"""Optional Git, protected-file, and read-only execution policy."""
from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..project.policy import protected_paths as policy_protected_paths
from ..errors import RunnerError
from ..utils.files import copy_ignore, digest
from ..bootstrap import current_runtime
from .contracts import HookViolation

from ..project.files import excluded_dirs, restore_project_changes, tree_manifest

BLOCKED_GIT_SUBCOMMANDS = frozenset({"add", "commit", "push"})
_VALUE_OPTIONS = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace",
    "--super-prefix", "--config-env", "--exec-path",
})
_VALUE_PREFIXES = tuple(option + "=" for option in _VALUE_OPTIONS if option.startswith("--"))
ProtectedData = bytes | Path | None


def git_subcommand(args: list[str]) -> str:
    index = 0
    while index < len(args):
        value = args[index]
        if value in _VALUE_OPTIONS:
            index += 2
            continue
        if value.startswith(_VALUE_PREFIXES) or value.startswith("-"):
            index += 1
            continue
        return value.lower()
    return ""


def _guarded_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    real_git = shutil.which("git", path=env.get("PATH"))
    if not real_git:
        return env
    guard = _guard_dir(Path(real_git).resolve())
    env["PATH"] = str(guard) + os.pathsep + env.get("PATH", "")
    return env


def _guarded_command(command: Sequence[str], environment: Mapping[str, str]) -> list[str]:
    values = list(command)
    if os.name != "nt" or not values:
        return values
    if Path(values[0]).name.lower() not in {"git", "git.exe", "git.cmd"}:
        return values
    guard_root = environment.get("PATH", "").split(os.pathsep, 1)[0]
    wrapper = Path(guard_root) / "git.cmd"
    if wrapper.is_file():
        values[0] = str(wrapper)
    return values


def _guard_dir(real_git: Path) -> Path:
    key = hashlib.sha256(f"{real_git}\0{sys.executable}".encode()).hexdigest()[:20]
    root = Path(tempfile.gettempdir()) / f"ai-task-runner-git-guard-{key}"
    root.mkdir(parents=True, exist_ok=True)
    helper = root / "guard.py"
    package_root = Path(__file__).resolve().parents[2]
    helper.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(package_root)!r})\n"
        "from runner.plugins.safety import _guard_main\n"
        "if __name__ == '__main__': raise SystemExit(_guard_main())\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        wrapper = root / "git.cmd"
        wrapper.write_text(f'@"{sys.executable}" "{helper}" "{real_git}" %*\r\n', encoding="utf-8")
    else:
        wrapper = root / "git"
        wrapper.write_text(
            "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " "
            + shlex.quote(str(helper)) + " " + shlex.quote(str(real_git)) + ' "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return root


def _guard_main() -> int:
    import subprocess
    if len(sys.argv) < 2:
        return 2
    real_git, args = sys.argv[1], sys.argv[2:]
    subcommand = git_subcommand(args)
    if subcommand in BLOCKED_GIT_SUBCOMMANDS:
        print(f"AI Task Runner blocked 'git {subcommand}': human review is required.", file=sys.stderr)
        return 126
    return subprocess.run([real_git, *args], check=False).returncode


def runner_source_files() -> list[Path]:
    package_root = Path(__file__).resolve().parents[1]
    root = package_root.parent
    result = [package_root]
    entry = root / "ai_task_runner.py"
    if entry.is_file():
        result.insert(0, entry)
    return result


def normalize_paths(paths: Sequence[Path]) -> list[Path]:
    roots: list[Path] = []
    for path in sorted({Path(value).resolve() for value in paths}, key=lambda value: (len(value.parts), str(value))):
        if not any(path == root or root in path.parents for root in roots):
            roots.append(path)
    return roots


def _snapshot_data(path: Path) -> ProtectedData:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_dir() and not path.is_symlink():
        backup_root = Path(tempfile.mkdtemp(prefix="ai-task-runner-protect-"))
        backup = backup_root / "snapshot"
        shutil.copytree(path, backup, symlinks=True)
        return backup
    return path.read_bytes()


def snapshot(paths: Sequence[Path]) -> dict[Path, tuple[str | None, ProtectedData]]:
    return {path: (digest(path), _snapshot_data(path)) for path in paths}


def changed_snapshot_paths(saved: dict[Path, tuple[str | None, ProtectedData]]) -> list[str]:
    return [str(path) for path, (old_hash, _data) in saved.items() if digest(path) != old_hash]


def restore_changed(saved: dict[Path, tuple[str | None, ProtectedData]]) -> list[str]:
    changed: list[str] = []
    backup_roots = [old_data.parent for _path, (_hash, old_data) in saved.items() if isinstance(old_data, Path)]
    try:
        for path, (old_hash, old_data) in saved.items():
            if digest(path) == old_hash:
                continue
            changed.append(str(path))
            if path.exists() or path.is_symlink():
                shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
            if old_data is None:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(old_data, Path):
                shutil.copytree(old_data, path, symlinks=True)
            else:
                path.write_bytes(old_data)
        return changed
    finally:
        for backup_root in backup_roots:
            shutil.rmtree(backup_root, ignore_errors=True)


@dataclass
class _Token:
    protected_snapshot: dict[Any, Any]
    before: dict[str, tuple[str, str | None]] | None = None
    backup_root: Path | None = None
    backup: Path | None = None


class SafetyHook:
    def _protected(self, root: Path) -> list[Path]:
        runtime = current_runtime()
        config = runtime.config
        values: list[Path] = [*runner_source_files(), *runtime.resources]
        for value in (config.goal_file, config.ai_validator_prompt_file):
            if value:
                values.append(Path(value).resolve())
        if config.validator and str(config.validator).lower() != "ai":
            values.append(Path(config.validator).resolve())
        values.append(root / config.work_dir / "state.json")
        values.extend(policy_protected_paths(root))
        values.extend(Path(value).resolve() for value in config.protect_files)
        return normalize_paths(values)

    def before_execution(self, context) -> _Token:
        protected_snapshot = snapshot(self._protected(context.root))
        if context.mode != "readonly":
            return _Token(protected_snapshot)
        excluded = excluded_dirs(context.root, context.work)
        before = tree_manifest(context.root, excluded)
        backup_root = Path(tempfile.mkdtemp(prefix="ai-task-runner-readonly-"))
        backup = backup_root / "project"
        shutil.copytree(context.root, backup, symlinks=True, ignore=copy_ignore(excluded))
        return _Token(protected_snapshot, before, backup_root, backup)

    def wrap_change_detector(self, context, token: _Token, base):
        def changed() -> bool:
            protected_changed = changed_snapshot_paths(token.protected_snapshot)
            if protected_changed:
                raise RunnerError("protected file modified during model call: " + ", ".join(protected_changed))
            return base()
        return changed

    def after_execution(self, context, token: _Token) -> list[HookViolation]:
        project_changed: list[str] = []
        protected_changed: list[str] = []
        try:
            if token.before is not None and token.backup is not None:
                after = tree_manifest(context.root, excluded_dirs(context.root, context.work))
                project_changed = sorted(
                    path for path in set(token.before) | set(after)
                    if token.before.get(path) != after.get(path)
                )
                if project_changed:
                    restore_project_changes(context.root, token.backup, project_changed)
        finally:
            if token.backup_root is not None:
                shutil.rmtree(token.backup_root, ignore_errors=True)
            protected_changed = restore_changed(token.protected_snapshot)
        violations: list[HookViolation] = []
        if protected_changed:
            violations.append(HookViolation("protected file modified and restored: " + ", ".join(protected_changed), "protected", tuple(protected_changed)))
        if project_changed:
            violations.append(HookViolation(f"{context.actor} modified files and they were restored: " + ", ".join(project_changed), "readonly", tuple(project_changed)))
        return violations

    def process_environment(self, environment):
        return _guarded_environment(environment)

    def process_command(self, command, environment):
        return _guarded_command(command, environment)

    def instructions(self, root: Path) -> str:
        protected = self._protected(root)
        if not protected:
            return ""
        paths = "\n".join(f"- {path}" for path in protected)
        return (
            "Safety rules:\n"
            "- Never modify runner state, runner source, validator inputs, backend-owned rules, or other protected paths listed below.\n"
            "- Never run `git add`, `git commit`, or `git push`; Git acceptance and publication are human-review actions. Read-only Git commands are allowed.\n"
            "Protected runner-owned paths (do not modify):\n" + paths
        )


def register(runtime) -> None:
    runtime.hooks.add(SafetyHook())


__all__ = ["BLOCKED_GIT_SUBCOMMANDS", "SafetyHook", "git_subcommand", "normalize_paths", "register", "restore_changed", "runner_source_files", "snapshot"]
