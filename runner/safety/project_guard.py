"""Compatibility facade over generic execution/project-state primitives."""
from __future__ import annotations

from pathlib import Path

from ..errors import RunnerError
from ..extensions.safety import (
    _changed_snapshot_paths as changed_snapshot_paths,
    _normalize_paths as normalize_protected_paths,
    _restore_changed as restore_changed,
    _runner_source_files as runner_source_files,
    _snapshot as snapshot,
)
from ..runtime.project_state import (
    changed_project_files,
    cleanup_stale_artifacts,
    project_fingerprint,
    project_manifest,
    progress_key,
)


def protected_change_detector(saved, base=None):
    def changed():
        paths = changed_snapshot_paths(saved)
        if paths:
            raise RunnerError("protected file modified during model call: " + ", ".join(paths))
        return bool(base and base())
    return changed


def protected_ask(agent, prompt, protected, idle_timeout_after_change=0, change_detected=None):
    saved = snapshot(protected)
    output = None
    error = None
    try:
        output = agent.ask(prompt, idle_timeout_after_change, protected_change_detector(saved, change_detected))
    except BaseException as caught:
        error = caught
    finally:
        changed = restore_changed(saved)
    if changed:
        raise RunnerError("protected file modified during model call: " + ", ".join(changed)) from error
    if error is not None:
        raise error
    return output, changed


def readonly_project_call(action, root: Path, work: Path):
    from tempfile import TemporaryDirectory
    import shutil
    from ..runtime.project_state import copy_ignore, excluded_dirs, restore_project_changes, tree_manifest

    excluded = excluded_dirs(root, work)
    before = tree_manifest(root, excluded)
    with TemporaryDirectory(prefix="ai-task-runner-readonly-") as temp:
        backup = Path(temp) / "project"
        shutil.copytree(root, backup, symlinks=True, ignore=copy_ignore(excluded))
        result = action()
        after = tree_manifest(root, excluded)
        changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
        if changed:
            restore_project_changes(root, backup, changed)
    return result, changed


__all__ = [
    "changed_project_files", "changed_snapshot_paths", "cleanup_stale_artifacts",
    "normalize_protected_paths", "progress_key", "project_fingerprint", "project_manifest",
    "protected_ask", "protected_change_detector", "readonly_project_call",
    "restore_changed", "runner_source_files", "snapshot",
]
