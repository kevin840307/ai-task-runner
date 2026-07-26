"""Reusable helpers for state, prompts, validation, retry, and terminal UI."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypeVar

from agent import AgentClient
from errors import RunnerError
from runner_models import RunState, Task
from process_control import run_process
from version import __version__


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
    root = Path(__file__).resolve().parent
    files = [
        root / "ai_task_runner.py",
        root / "runner_api.py",
        root / "api.py",
        root / "agent.py",
        root / "errors.py",
        root / "runner_models.py",
        root / "models.py",
        root / "runner_core.py",
        root / "runner_support.py",
        root / "version.py",
        root / "process_control.py",
        *sorted((root / "backends").glob("*.py")),
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
            change_detected,
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


def project_outline(root: Path, limit: int = 120) -> str:
    """Return a compact read-only project outline for planning prompts."""
    excluded = set(READONLY_EXCLUDE_DIRS) | {".qwen"}
    entries: list[str] = []
    for current, directories, files in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = [
            name for name in directories
            if name not in excluded and not name.startswith(".")
        ]
        for name in sorted(files):
            if name.startswith("."):
                continue
            relative = (base / name).relative_to(root).as_posix()
            entries.append(relative)
            if len(entries) >= limit:
                entries.append("...")
                return "\n".join(entries)
    return "\n".join(entries) if entries else "(no project files)"


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
) -> tuple[str, list[str], list[str]]:
    file_snapshot = snapshot(protected)
    try:
        output, project_changed = readonly_project_call(
            lambda: agent.ask(prompt),
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


def rules(root: Path, protected: Sequence[Path]) -> str:
    protected_names = "\n".join(f"- {path}" for path in protected)
    return f"""Hard rules:
- You may READ files anywhere when necessary.
- You may WRITE/CREATE/DELETE files only inside project root: {root}
- Never modify these protected files:
{protected_names}
- Never modify runner state directly. Python owns task state.
- Before planning or changing code, inspect the relevant project structure, entry points, dependencies, public interfaces, conventions, and existing tests.
- Prefer the smallest maintainable change that fully satisfies the current task.
- Prefer simple standard-library or existing project facilities over hand-written complex logic when they satisfy the goal and are safe to use.
- Preserve existing behavior, public interfaces, file formats, and dependencies unless the goal explicitly requires changing them.
- Avoid unrelated refactoring, duplication, speculative features, and unnecessary dependencies.
- Do not ask questions or wait for user input. Inspect available files, make the safest reasonable assumption, and continue.
- Do not invent files, credentials, APIs, test results, or facts. Report unavailable evidence honestly.
"""


def planning_rules(work: Path) -> str:
    return f"""Hard rules:
- You may READ files anywhere when necessary.
- During planning, write/create/delete files only inside runner work directory: {work}
- Never modify validator files, runner state, runner source files, backend rules, or project implementation files during planning.
- Python owns task order and completion state.
- Inspect the relevant project structure, entry points, dependencies, public interfaces, conventions, and existing tests before planning.
- Prefer the smallest maintainable change that fully satisfies the current task.
- Preserve existing behavior, public interfaces, file formats, and dependencies unless the goal explicitly requires changing them.
- Avoid unrelated refactoring, duplication, speculative features, and unnecessary dependencies.
- Do not ask questions or wait for user input. Inspect available files, make the safest reasonable assumption, and continue.
- Do not invent files, credentials, APIs, test results, or facts. Report unavailable evidence honestly.
"""


def task_spec(task: Task) -> dict[str, Any]:
    return {
        "title": task.title,
        "description": task.description,
        "acceptance_criteria": task.acceptance_criteria,
    }


def completed_titles(state: RunState) -> list[str]:
    return [task.title for task in state.tasks if task.status == "completed"]


def plan_prompt(
    goal: str,
    root: Path,
    state: RunState,
    protected: Sequence[Path],
    work: Path | None = None,
) -> str:
    progress = {
        "cycle": state.cycle,
        "validator_feedback": state.validator_output[-8000:],
        "completed_tasks": completed_titles(state),
    }
    outline = project_outline(root)
    work_dir = work or root / ".ai-task-runner"
    return planning_rules(work_dir) + f"""
Plan only the remaining work for this goal:
{goal}

Project root to inspect:
{root}

Project files:
{outline}

Progress:
{json.dumps(progress, ensure_ascii=False)}

Use the project outline and progress above for planning; do not read files during planning.
Choose task count from actual complexity; there is no limit.
If the goal lists numbered deliverables, usually create one ordered task per deliverable.
If the goal implies multiple deliverables such as source files, CLI behavior, generated outputs, tests, validators, or documentation, split them into ordered tasks.
Right-size the task list: trivial goals can be one task, small tools usually need a few deliverable-sized tasks, and broad goals need more tasks grouped by verifiable outcomes.
Do not create tasks for pure constraints or instructions such as not asking questions, keeping code small, or verifying work; put those into acceptance criteria instead.
Each task must be ordered, independently executable, meaningful, and have clear acceptance criteria.
Avoid unrelated work in one task and tiny mechanical steps.
If planning notes are written, they may be JSON or Markdown files only under this runner work directory: {work_dir}
Prefer returning the final tasks JSON directly instead of writing files during planning.
Do not create, edit, delete, or rename project implementation files during planning; implementation happens only after tasks are returned.
Do not use Qwen todo tools during planning; Python owns task order and completion state.
Do not implement, ask questions, or wait for input. Make reasonable assumptions from the project.
Return at least one task. Never return an empty tasks array.

Return only this JSON shape, without Markdown or explanation:
{{"tasks":[{{"title":"Implement requested change","description":"Make the smallest maintainable project change needed to satisfy the goal.","acceptance_criteria":["The requested behavior is implemented","Relevant checks pass"]}}]}}
"""


def execution_prompt(
    state: RunState,
    root: Path,
    protected: Sequence[Path],
    strategy_note: str = "",
    validator_hint: str = "",
) -> str:
    task = state.tasks[state.current]
    context = {
        "goal": state.goal,
        "completed_tasks": completed_titles(state),
        "validator_feedback": format_validator_feedback(
            state.validator_output,
            2000,
        ),
    }
    strategy = f"\nRecovery instruction:\n{strategy_note}\n" if strategy_note else ""
    previous = (
        f"\nPrevious attempt output or diagnostic:\n{task.last_output[-2000:]}\n"
        if task.last_output
        else ""
    )
    validator_reference = (
        f"\nValidator reference:\n{validator_hint}\n"
        if validator_hint
        else ""
    )
    return rules(root, protected) + f"""
Execute only the current task below. Do not start later tasks.
Use this order: inspect relevant project files, make the smallest maintainable change, run focused local checks, then fix the first failure if any.
If Run context includes validator_feedback, treat it as authoritative and fix the reported problem before doing other work.
Create only files that are required by the task or clearly useful for validation.
Do not create scripts, commands, or files whose purpose is to update runner state, task status, reviews, attempts, or `.ai-task-runner`; only implement the requested project behavior.
Prefer file edit/write tools for creating or changing files. Use shell commands mainly for checks, tests, and small local scripts.
Do not delegate to subagents, background agents, scaffolding skills, or app-generation skills. Complete the current task directly in this session.
Do not use computer-use, desktop, browser, or app-launch tools; this runner works through project files and shell checks.
If a required file or command is missing, create or fix it instead of repeating the same read/check command. Do not call the same tool repeatedly with identical arguments after it returns the same result.
You may read validator files to understand expected behavior, but never modify them or hardcode validator internals. Python runs the final validator after review; use validator feedback and the validator reference only to guide the project implementation.
Do not ask questions or wait for input. Resolve ambiguity with the safest reasonable assumption and continue.

Run context:
{json.dumps(context, ensure_ascii=False)}
{validator_reference}

Task:
{json.dumps(task_spec(task), ensure_ascii=False)}
{previous}
{strategy}
Finish with a factual summary of changed files and checks.
"""


def review_prompt(
    state: RunState,
    root: Path,
    protected: Sequence[Path],
    output: str,
) -> str:
    task = state.tasks[state.current]
    feedback = format_validator_feedback(state.validator_output, 2000)
    validator_section = (
        f"\nLatest validator feedback to consider:\n{feedback}\n"
        if feedback
        else ""
    )
    return rules(root, protected) + f"""
Review only. Do not edit project files or ask questions.
Inspect the project and verify every acceptance criterion. Also verify the change is scoped, maintainable, and preserves relevant existing behavior. You may run checks; generated artifacts are temporary and will be discarded.
If validator feedback is provided, it is authoritative evidence from the final check. Do not mark the task complete unless the reported failure is fixed or clearly impossible.

Task:
{json.dumps(task_spec(task), ensure_ascii=False)}

Executor report:
{output[-5000:]}
{validator_section}

Return only JSON, without Markdown or explanation:
{{"completed":true,"reason":"All acceptance criteria are satisfied.","missing_items":[]}}
"""


def format_validator_feedback(feedback: str, limit: int = 2000) -> str:
    text = feedback.strip()
    if not text:
        return ""
    return (
        "Validator feedback below is the final validator's failure report. "
        "It describes the current rejected behavior or output, not the desired "
        "result. If it says 'unexpected ...' and shows a block, that block is "
        "the actual bad value to change away from. Fix the first reported "
        "failure, then preserve the original goal. If the bad value is in a "
        "generated output or validator-created sample file, fix the program "
        "behavior that produces it; do not only edit the current generated "
        "file.\n"
        + text[-limit:]
    )


def ai_validator_prompt(
    goal: str,
    root: Path,
    protected: Sequence[Path],
    custom: str = "",
) -> str:
    extra = (
        f"\nAdditional validation instructions:\n{custom}\n"
        if custom
        else ""
    )
    return rules(root, protected) + f"""
Final validation in a fresh independent session. Do not edit project files.
Goal: {goal}
Inspect the current project and decide whether the goal is fully complete and usable.
Check implementation completeness, consistency, likely defects, and relevant tests or build results. You may run checks; generated artifacts are temporary and will be discarded.{extra}
Do not ask questions or wait for input. Make a verdict from available evidence.
Return only JSON, without Markdown or explanation:
{{"passed":true,"reason":"The goal is fully implemented and verified.","missing_items":[]}}
"""


class LiveUI:
    """Human terminal UI plus optional machine-readable progress events."""

    FRAMES = "|/-\\"

    def __init__(
        self,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
        json_events: bool = False,
        human_output: bool = True,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        self.event_callback = event_callback
        self.json_events = json_events
        self.human_output = human_output
        self.context = dict(context or {})
        self.enabled = human_output and not json_events and sys.stdout.isatty()
        self.state: RunState | None = None
        self.status = "準備中"
        self.detail = ""
        self._frame = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def bind(self, state: RunState) -> None:
        self.state = state
        self.draw()
        self._emit("runner.progress")

    def set(self, status: str, detail: str = "") -> None:
        with self._lock:
            self.status = status
            self.detail = detail
        self.draw()
        self._emit("runner.status")

    def draw(self) -> None:
        if not self.enabled or not self.state:
            return
        with self._lock:
            state = self.state
            status = self.status
            detail = self.detail
            spinner = (
                self.FRAMES[self._frame % len(self.FRAMES)]
                if self._thread
                else " "
            )
        completed_count = sum(
            task.status == "completed" for task in state.tasks
        )
        lines = [
            f"AI Task Runner  Cycle {state.cycle}  "
            f"Progress {completed_count}/{len(state.tasks)}",
            "",
        ]
        for index, task in enumerate(state.tasks):
            mark = self._task_mark(state, index, task)
            lines.append(f"  [{mark}] {index + 1}. {task.title}")
        lines.extend(["", f"  {spinner} {status}"])
        if detail:
            lines.append(f"    {detail}")
        sys.stdout.write("\x1b[2J\x1b[H" + "\n".join(lines) + "\n")
        sys.stdout.flush()

    def _emit(self, event_type: str) -> None:
        event: dict[str, Any] = {
            "schema_version": 1,
            "runner_version": __version__,
            "type": event_type,
            "timestamp": time.time(),
            "status": self.status,
            "detail": self.detail,
            **self.context,
        }
        if self.state is not None:
            event.update({
                "run_id": self.state.run_id,
                "cycle": self.state.cycle,
                "current": self.state.current,
                "completed": self.state.completed,
                "tasks": [
                    {
                        "id": task.id,
                        "title": task.title,
                        "status": task.status,
                        "attempts": task.attempts,
                    }
                    for task in self.state.tasks
                ],
            })
        if self.event_callback is not None:
            try:
                self.event_callback(event)
            except Exception:
                # Integration/UI failures must not stop the automation loop.
                pass
        if self.json_events:
            try:
                print(json.dumps(event), flush=True)
            except (BrokenPipeError, OSError):
                # A disconnected UI must not stop the automation loop.
                self.json_events = False

    @staticmethod
    def _task_mark(state: RunState, index: int, task: Task) -> str:
        if task.status == "completed":
            return "x"
        if index == state.current and not state.completed:
            return ">"
        return " "

    def start(self, status: str, detail: str = "") -> None:
        self.stop()
        self.set(status, detail)
        if not self.enabled:
            if self.human_output and not self.json_events:
                message = f"{status}: {detail}" if detail else status
                print(message, flush=True)
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        while not self._stop.wait(0.12):
            self._frame += 1
            self.draw()

    def stop(self, status: str | None = None, detail: str = "") -> None:
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=0.5)
            self._thread = None
        if status:
            self.set(status, detail)


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


def show_todo(state: RunState, ui: LiveUI) -> None:
    ui.bind(state)


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
