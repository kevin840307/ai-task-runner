"""Reusable helpers for state, prompts, validation, retry, and terminal UI."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Sequence, TypeVar

from .agent import AgentClient
from .errors import RunnerError
from .models import RunState, Task
from .process_control import run_process
from .prompting import (
    ai_validator_prompt,
    bounded_text,
    completed_titles,
    execution_prompt,
    format_validator_feedback,
    plan_prompt,
    planning_rules,
    project_outline,
    render_prompt_template,
    review_prompt,
    rules,
    task_spec,
)
from .ui import LiveUI, show_todo, supports_ansi_screen


T = TypeVar("T")
READONLY_EXCLUDE_DIRS = frozenset({
    ".git",
    ".ai-task-runner",
    ".idea",
    ".venv",
    ".vs",
    "__pycache__",
    "bin",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "obj",
    "target",
})
MAX_TASK_OUTPUT_CHARS = 10_000
MAX_VALIDATOR_OUTPUT_CHARS = 20_000
MAX_RESULT_REASON_CHARS = 4_000
MAX_MISSING_ITEMS = 100
MAX_MISSING_ITEM_CHARS = 1_000
NO_PROGRESS_LIMIT = 3
STALE_TEMP_SECONDS = 7 * 24 * 60 * 60


def runner_source_files() -> list[Path]:
    """Return all Python files that implement the runner itself."""
    package_root = Path(__file__).resolve().parent
    root = package_root.parent
    root_modules = (
        "ai_task_runner.py",
        "ai_task_runner_validator.py",
    )
    files = [
        *(root / name for name in root_modules),
        *sorted(package_root.glob("*.py")),
        *sorted((package_root / "backends").glob("*.py")),
    ]
    return [path for path in files if path.is_file()]


def write_json(path: Path, data: Any) -> None:
    """Atomically write indented UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(paths: Sequence[Path]) -> dict[Path, tuple[str | None, bytes | None]]:
    return {
        path: (digest(path), path.read_bytes() if path.exists() else None)
        for path in paths
    }


def restore_changed(
    file_snapshot: dict[Path, tuple[str | None, bytes | None]],
) -> list[str]:
    """Restore changed protected files and return their paths."""
    changed: list[str] = []
    for path, (old_hash, old_data) in file_snapshot.items():
        if digest(path) == old_hash:
            continue
        changed.append(str(path))
        if old_data is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(old_data)
    return changed


def changed_snapshot_paths(
    file_snapshot: dict[Path, tuple[str | None, bytes | None]],
) -> list[str]:
    """Return protected files that differ from a prior snapshot."""
    return [
        str(path)
        for path, (old_hash, _old_data) in file_snapshot.items()
        if digest(path) != old_hash
    ]


def protected_change_detector(
    file_snapshot: dict[Path, tuple[str | None, bytes | None]],
    change_detected: Callable[[], bool] | None,
) -> Callable[[], bool]:
    def changed() -> bool:
        protected_changed = changed_snapshot_paths(file_snapshot)
        if protected_changed:
            raise RunnerError(
                "protected file modified during model call: "
                + ", ".join(protected_changed)
            )
        return change_detected() if change_detected is not None else False

    return changed


def parse_json(text: str) -> dict[str, Any]:
    """Extract the first valid JSON object from plain or fenced model output."""
    candidates = [
        text.strip(),
        *re.findall(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            text,
            re.DOTALL | re.IGNORECASE,
        ),
    ]
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    start = text.find("{")
    while start >= 0:
        candidate = _balanced_json_object(text, start)
        if candidate is not None:
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(value, dict):
                    return value
        start = text.find("{", start + 1)
    raise RunnerError("AI response has no valid JSON object")


def _balanced_json_object(text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def protected_ask(
    agent: AgentClient,
    prompt: str,
    protected: Sequence[Path],
    idle_timeout_after_change: float = 0,
    change_detected: Callable[[], bool] | None = None,
) -> tuple[str, list[str]]:
    file_snapshot = snapshot(protected)
    output: str | None = None
    try:
        output = agent.ask(
            prompt,
            idle_timeout_after_change,
            protected_change_detector(file_snapshot, change_detected),
        )
    finally:
        changed = restore_changed(file_snapshot)
    return output, changed


def _readonly_excludes(root: Path, work: Path) -> set[str]:
    excluded = set(READONLY_EXCLUDE_DIRS)
    if work.is_relative_to(root):
        excluded.add(work.relative_to(root).parts[0])
    return excluded


def _tree_manifest(
    root: Path,
    excluded_dirs: set[str],
) -> dict[str, tuple[str, str | None]]:
    result: dict[str, tuple[str, str | None]] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = [
            name for name in directories if name not in excluded_dirs
        ]
        for name in list(directories):
            path = base / name
            relative_path = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative_path] = ("link", os.readlink(path))
                directories.remove(name)
            else:
                result[relative_path] = ("dir", "")
        for name in files:
            path = base / name
            relative_path = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative_path] = ("link", os.readlink(path))
            else:
                result[relative_path] = ("file", digest(path))
    return result


def project_fingerprint(root: Path, work: Path) -> str:
    manifest = _tree_manifest(root, _readonly_excludes(root, work))
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def progress_key(
    root: Path,
    work: Path,
    missing_items: Sequence[str],
) -> str:
    payload = {
        "project": project_fingerprint(root, work),
        "missing_items": list(missing_items),
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _copy_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        target.symlink_to(
            os.readlink(source),
            target_is_directory=source.is_dir(),
        )
    elif source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)


def _restore_project_changes(
    root: Path,
    backup: Path,
    changed: Sequence[str],
) -> None:
    paths = [Path(relative) for relative in changed]
    for relative in sorted(paths, key=lambda value: len(value.parts), reverse=True):
        _remove_path(root / relative)
    for relative in sorted(paths, key=lambda value: len(value.parts)):
        source = backup / relative
        target = root / relative
        if target.exists() or target.is_symlink():
            continue
        if source.exists() or source.is_symlink():
            _copy_path(source, target)


def _copy_ignore(excluded_dirs: set[str]) -> Callable[[str, list[str]], list[str]]:
    def ignore(source: str, names: list[str]) -> list[str]:
        base = Path(source)
        return [
            name
            for name in names
            if name in excluded_dirs and (base / name).is_dir()
        ]

    return ignore


def readonly_project_call(
    action: Callable[[], T],
    root: Path,
    work: Path,
) -> tuple[T, list[str]]:
    """Run an action and restore source changes while ignoring build caches."""
    excluded_dirs = _readonly_excludes(root, work)
    before = _tree_manifest(root, excluded_dirs)
    with tempfile.TemporaryDirectory(prefix="ai-task-runner-readonly-") as temp:
        backup = Path(temp) / "project"
        shutil.copytree(
            root,
            backup,
            symlinks=True,
            ignore=_copy_ignore(excluded_dirs),
        )
        try:
            result = action()
        finally:
            after = _tree_manifest(root, excluded_dirs)
            changed = sorted(
                path
                for path in set(before) | set(after)
                if before.get(path) != after.get(path)
            )
            if changed:
                _restore_project_changes(root, backup, changed)
    return result, changed


def readonly_ask(
    agent: AgentClient,
    prompt: str,
    root: Path,
    work: Path,
    protected: Sequence[Path],
    timeout: int | None = None,
) -> tuple[str, list[str], list[str]]:
    file_snapshot = snapshot(protected)
    try:
        output, project_changed = readonly_project_call(
            lambda: agent.ask(prompt, timeout=timeout),
            root,
            work,
        )
    finally:
        protected_changed = restore_changed(file_snapshot)
    return output, protected_changed, project_changed


def cleanup_stale_artifacts(
    work: Path,
    temp_root: Path | None = None,
    older_than: float = STALE_TEMP_SECONDS,
) -> None:
    """Remove interrupted atomic writes and old readonly backups."""
    work.mkdir(parents=True, exist_ok=True)
    for path in work.glob("*.tmp"):
        _remove_path(path)

    cutoff = time.time() - older_than
    base = temp_root or Path(tempfile.gettempdir())
    for path in base.glob("ai-task-runner-readonly-*"):
        try:
            if path.stat().st_mtime < cutoff:
                _remove_path(path)
        except OSError:
            continue


def retry_model_call(
    action: Callable[[], T],
    ui: LiveUI,
    status: str,
    detail: str,
    wait: float,
    max_wait: float,
    max_errors: int = 0,
) -> T:
    delay = max(0.0, wait)
    errors = 0
    while True:
        ui.start(status, detail)
        try:
            return action()
        except RunnerError as error:
            errors += 1
            ui.stop("模型呼叫異常，將自動重試", str(error)[-500:])
            if max_errors and errors >= max_errors:
                raise RunnerError(
                    f"model call failed {errors} times; "
                    "retrying from the runner task flow: "
                    f"{str(error)[-1000:]}"
                ) from error
            if delay:
                time.sleep(delay)
                delay = min(max_wait, max(wait, delay * 2))
        finally:
            ui.stop()
def require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunnerError(f"{field_name} must be a non-empty string")
    return value.strip()


def require_string_list(
    value: Any,
    field_name: str,
    allow_empty: bool = True,
) -> list[str]:
    if not isinstance(value, list):
        raise RunnerError(f"{field_name} must be an array of strings")
    result = [
        require_non_empty_string(item, f"{field_name}[{index}]")
        for index, item in enumerate(value, 1)
    ]
    if not allow_empty and not result:
        raise RunnerError(f"{field_name} must not be empty")
    return result


def parse_tasks(text: str, cycle: int) -> list[Task]:
    raw_tasks = parse_json(text).get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise RunnerError("tasks must be a non-empty array")

    tasks: list[Task] = []
    for index, item in enumerate(raw_tasks, 1):
        if not isinstance(item, dict):
            raise RunnerError(f"tasks[{index}] must be an object")
        title = require_non_empty_string(
            item.get("title"),
            f"tasks[{index}].title",
        )
        description = require_non_empty_string(
            item.get("description"),
            f"tasks[{index}].description",
        )
        criteria_value = item.get("acceptance_criteria", item.get("accept_criteria"))
        criteria = require_string_list(
            criteria_value,
            f"tasks[{index}].acceptance_criteria",
            allow_empty=False,
        )
        tasks.append(
            Task(
                id=f"c{cycle:02d}-t{index:03d}",
                title=title,
                description=description,
                acceptance_criteria=criteria,
            )
        )
    return tasks


def _bounded_result_text(value: Any, field_name: str) -> str:
    return require_non_empty_string(value, field_name)[:MAX_RESULT_REASON_CHARS]


def _bounded_missing_items(value: Any, field_name: str) -> list[str]:
    items = require_string_list(value, field_name)[:MAX_MISSING_ITEMS]
    return [item[:MAX_MISSING_ITEM_CHARS] for item in items]


def parse_review(text: str) -> dict[str, Any]:
    value = parse_json(text)
    if not isinstance(value.get("completed"), bool):
        raise RunnerError("review.completed must be boolean")
    return {
        "completed": value["completed"],
        "reason": _bounded_result_text(value.get("reason"), "review.reason"),
        "missing_items": _bounded_missing_items(
            value.get("missing_items", []),
            "review.missing_items",
        ),
    }


def parse_ai_validation(text: str) -> dict[str, Any]:
    value = parse_json(text)
    if not isinstance(value.get("passed"), bool):
        raise RunnerError("validator.passed must be boolean")
    return {
        "passed": value["passed"],
        "reason": _bounded_result_text(
            value.get("reason"),
            "validator.reason",
        ),
        "missing_items": _bounded_missing_items(
            value.get("missing_items", []),
            "validator.missing_items",
        ),
        "checks_run": _bounded_missing_items(
            value.get("checks_run", []),
            "validator.checks_run",
        ),
        "suggested_checks": _bounded_missing_items(
            value.get("suggested_checks", []),
            "validator.suggested_checks",
        ),
    }


def run_file_validator(
    path: Path,
    root: Path,
    state_file: Path,
    timeout: int,
    extra_args: Sequence[str],
    protected: Sequence[Path],
) -> tuple[bool, str]:
    file_snapshot = snapshot(protected)
    clear_validator_reports(root)
    command = [
        sys.executable,
        str(path),
        "--project-root",
        str(root),
        "--state-file",
        str(state_file),
        *extra_args,
    ]
    try:
        result = run_process(command, root, timeout)
    except OSError as error:
        restore_changed(file_snapshot)
        raise RunnerError(f"validator failed: {error}") from error

    changed = restore_changed(file_snapshot)
    changed_message = (
        "Protected file changed during validation and was restored: "
        + ", ".join(changed)
        if changed
        else ""
    )
    if result.timed_out:
        details = [
            f"validator timeout after {timeout} seconds",
            result.output[-4000:].strip(),
            changed_message,
        ]
        return False, "\n".join(item for item in details if item)
    if changed_message:
        return False, changed_message
    return result.return_code == 0, result.output


def clear_validator_reports(root: Path) -> None:
    reports = root / ".ai-task-runner" / "validator-reports"
    if not reports.exists() and not reports.is_symlink():
        return
    try:
        if reports.is_symlink() or reports.is_file():
            reports.unlink()
        else:
            shutil.rmtree(reports)
    except OSError as error:
        raise RunnerError(f"failed to clear validator reports: {error}") from error
