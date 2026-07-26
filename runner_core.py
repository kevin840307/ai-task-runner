"""Core task execution flow shared by every AI backend."""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

from agent import AgentClient
from errors import RunnerError
from runner_models import RunState, Task
from version import __version__
from runner_support import (
    LiveUI,
    MAX_TASK_OUTPUT_CHARS,
    MAX_VALIDATOR_OUTPUT_CHARS,
    NO_PROGRESS_LIMIT,
    cleanup_stale_artifacts,
    ai_validator_prompt,
    execution_prompt,
    parse_ai_validation,
    parse_review,
    parse_tasks,
    plan_prompt,
    protected_ask,
    progress_key,
    readonly_ask,
    retry_model_call,
    review_prompt,
    run_file_validator,
    runner_source_files,
    show_todo,
    write_json,
)


def run_ai_validator(
    args: argparse.Namespace,
    root: Path,
    work: Path,
    state: RunState,
    protected: Sequence[Path],
    ui: LiveUI,
) -> tuple[bool, str]:
    validator = AgentClient(
        backend=args.backend,
        command=args.command,
        root=root,
        extra_args=args.agent_arg,
        session_id="",
        timeout=args.agent_timeout,
    )

    def call() -> dict[str, Any]:
        raw, protected_changed, project_changed = readonly_ask(
            validator,
            ai_validator_prompt(
                state.goal,
                root,
                protected,
                args.validator_prompt,
            ),
            root,
            work,
            protected,
        )
        changed = [*protected_changed, *project_changed]
        if changed:
            raise RunnerError(
                "AI validator modified files and they were restored: "
                + ", ".join(changed)
            )
        return parse_ai_validation(raw)

    result = retry_model_call(
        call,
        ui,
        "正在執行最終 AI 驗證",
        "new session",
        args.retry_wait,
        args.retry_max_wait,
    )
    return result["passed"] is True, json.dumps(result, ensure_ascii=False)


def load_yaml_script(path: Path) -> list[dict[str, str]]:
    try:
        import yaml
    except ImportError as error:
        raise RunnerError(
            "YAML script requires PyYAML: pip install PyYAML"
        ) from error

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise RunnerError(f"invalid YAML script: {error}") from error

    if not isinstance(data, list) or not data:
        raise RunnerError("YAML script must be a non-empty array")

    items: list[dict[str, str]] = []
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise RunnerError(f"script item {index} must be an object")
        prompt = item.get("prompt") or item.get("goal")
        validator = item.get("validator")
        if not isinstance(prompt, str) or not prompt.strip():
            raise RunnerError(f"script item {index} requires prompt")
        if not isinstance(validator, str) or not validator.strip():
            raise RunnerError(
                f"script item {index} requires validator path or 'ai'"
            )
        items.append(
            {
                "prompt": prompt.strip(),
                "validator": validator.strip(),
                "validator_prompt": str(item.get("validator_prompt", "")),
            }
        )
    return items


def execute_script(args: argparse.Namespace) -> int:
    script = Path(args.script).resolve()
    if not script.is_file():
        raise RunnerError("invalid YAML script")

    items = load_yaml_script(script)
    total = len(items)
    for index, item in enumerate(items, 1):
        _script_event(args, "script.item_started", index, total, item)
        child = _script_item_args(args, item, index)
        child.script_index = index
        child.script_total = total
        code = execute(child)
        if code != 0:
            _script_event(
                args,
                "script.item_failed",
                index,
                total,
                item,
                exit_code=code,
            )
            return code
        _script_event(args, "script.item_completed", index, total, item)
    return 0


def _script_event(
    args: argparse.Namespace,
    event_type: str,
    index: int,
    total: int,
    item: dict[str, str],
    exit_code: int | None = None,
) -> None:
    event: dict[str, Any] = {
        "schema_version": 1,
        "runner_version": __version__,
        "type": event_type,
        "timestamp": time.time(),
        "script_index": index,
        "script_total": total,
        "prompt_preview": item["prompt"][:500],
    }
    if exit_code is not None:
        event["exit_code"] = exit_code

    callback = getattr(args, "event_callback", None)
    if callback is not None:
        try:
            callback(event)
        except Exception:
            # External UI/skill failures must not stop script execution.
            pass
    if getattr(args, "json_events", False):
        try:
            print(json.dumps(event, ensure_ascii=False), flush=True)
        except (BrokenPipeError, OSError):
            args.json_events = False
        return
    if not getattr(args, "human_output", True):
        return

    if event_type == "script.item_started":
        print(f"[Script {index}/{total}] {item['prompt']}", flush=True)
    elif event_type == "script.item_completed":
        print(f"[Script {index}/{total}] PASS", flush=True)
    else:
        print(
            f"[Script {index}/{total}] FAILED ({exit_code})",
            file=sys.stderr,
            flush=True,
        )


def _script_item_args(
    args: argparse.Namespace,
    item: dict[str, str],
    index: int,
) -> argparse.Namespace:
    child = copy.copy(args)
    child.script = None
    child.goal = item["prompt"]
    child.validator = item["validator"]
    child.validator_prompt = item["validator_prompt"]
    child.work_dir = str(Path(args.work_dir) / "script" / f"{index:03d}")

    state_file = (
        Path(args.project_root).resolve()
        / child.work_dir
        / "state.json"
    )
    child.resume = bool(args.resume and state_file.is_file())
    child.force_new = not child.resume
    return child


class TaskRunner:
    """Owns one goal, one main model session, and one state file."""

    def __init__(self, args: argparse.Namespace) -> None:
        if not args.validator:
            raise RunnerError("--validator is required unless --script is used")

        self.args = args
        self.root = Path(args.project_root).resolve()
        self.ai_validation = args.validator.lower() == "ai"
        self.validator = (
            None
            if self.ai_validation
            else Path(args.validator).resolve()
        )
        self.work = self.root / args.work_dir
        self.state_file = self.work / "state.json"

        self._validate_paths()
        cleanup_stale_artifacts(self.work)
        self.state = self._load_or_create_state()
        self.agent = AgentClient(
            backend=args.backend,
            command=args.command,
            root=self.root,
            extra_args=args.agent_arg,
            session_id=self.state.agent_session_id,
            timeout=args.agent_timeout,
        )
        self.backend_files = self.agent.prepare_project()
        if not args.resume:
            self._save_state()
        self.protected = self._build_protected_files()
        context = {
            "script_index": getattr(args, "script_index", None),
            "script_total": getattr(args, "script_total", None),
        }
        self.ui = LiveUI(
            event_callback=getattr(args, "event_callback", None),
            json_events=getattr(args, "json_events", False),
            human_output=getattr(args, "human_output", True),
            context={
                key: value
                for key, value in context.items()
                if value is not None
            },
        )
        self.ui.bind(self.state)

    def run(self) -> int:
        while not self.state.completed:
            self._plan_if_needed()
            task_code = self._run_pending_tasks()
            if task_code is not None:
                return task_code
            validation_code = self._validate_cycle()
            if validation_code is not None:
                return validation_code
        return 0

    def _validate_paths(self) -> None:
        if not self.root.is_dir():
            raise RunnerError("invalid project root or validator")
        if self.validator is not None and not self.validator.is_file():
            raise RunnerError("invalid project root or validator")

    def _build_protected_files(self) -> list[Path]:
        paths = [
            *([self.validator] if self.validator else []),
            self.state_file,
            *runner_source_files(),
            *self.backend_files,
            *[Path(value).resolve() for value in self.args.protect_file],
        ]
        return list(dict.fromkeys(paths))

    def _load_or_create_state(self) -> RunState:
        if self.args.resume:
            if not self.state_file.is_file():
                raise RunnerError(
                    f"resume state not found: {self.state_file}"
                )
            try:
                payload = json.loads(
                    self.state_file.read_text(encoding="utf-8")
                )
                state = RunState.load(payload)
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
                raise RunnerError(f"invalid resume state: {error}") from error
            if Path(state.project_root).resolve() != self.root:
                raise RunnerError(
                    "resume state belongs to a different project_root"
                )
            state.validator_output = (
                state.validator_output[-MAX_VALIDATOR_OUTPUT_CHARS:]
            )
            for task in state.tasks:
                task.last_output = task.last_output[-MAX_TASK_OUTPUT_CHARS:]
            return state
        if not self.args.goal:
            raise RunnerError("--goal is required")
        if self.state_file.exists() and not self.args.force_new:
            raise RunnerError("state exists; use --resume or --force-new")

        return RunState(
            run_id=str(uuid.uuid4()),
            goal=self.args.goal,
            project_root=str(self.root),
        )

    def _save_state(self) -> None:
        write_json(self.state_file, self.state.dump())

    def _save_session(self) -> None:
        self.state.agent_session_id = self.agent.session_id
        self._save_state()

    def _plan_if_needed(self) -> None:
        if self.state.tasks and self.state.current < len(self.state.tasks):
            return

        def plan_call() -> list[Task]:
            output, changed = protected_ask(
                self.agent,
                plan_prompt(
                    self.state.goal,
                    self.root,
                    self.state,
                    self.protected,
                ),
                self.protected,
            )
            if changed:
                raise RunnerError(
                    "AI modified protected files during planning: "
                    + ", ".join(changed)
                )
            return parse_tasks(output, self.state.cycle)

        planned = retry_model_call(
            plan_call,
            self.ui,
            "AI 正在理解並拆分任務",
            "",
            self.args.retry_wait,
            self.args.retry_max_wait,
        )
        completed = [
            task for task in self.state.tasks
            if task.status == "completed"
        ]
        self.state.agent_session_id = self.agent.session_id
        self.state.tasks = [*completed, *planned]
        self.state.current = len(completed)
        self._save_state()
        show_todo(self.state, self.ui)

    def _run_pending_tasks(self) -> int | None:
        while self.state.current < len(self.state.tasks):
            task = self.state.tasks[self.state.current]
            task.attempts += 1
            self._save_state()
            show_todo(self.state, self.ui)

            output = self._execute_current_task(task)
            task.last_output = output[-MAX_TASK_OUTPUT_CHARS:]
            self._save_session()

            review = self._review_current_task(task, output)
            task.last_review = review
            self._save_session()

            if review["completed"] is True:
                self._complete_current_task(task)
                continue

            task.status = "pending"
            self._record_no_progress(task, review)
            self._save_state()
            self.ui.set(
                "任務未完成，準備重試",
                review["reason"],
            )
            show_todo(self.state, self.ui)
            if (
                self.args.max_attempts
                and task.attempts >= self.args.max_attempts
            ):
                return 2
            if self.args.retry_delay:
                time.sleep(self.args.retry_delay)
        return None

    def _record_no_progress(
        self,
        task: Task,
        review: dict[str, Any],
    ) -> None:
        key = progress_key(
            self.root,
            self.work,
            review["missing_items"],
        )
        if key == task.progress_key:
            task.stagnant_attempts += 1
        else:
            task.progress_key = key
            task.stagnant_attempts = 1

    def _complete_current_task(self, task: Task) -> None:
        task.status = "completed"
        task.progress_key = ""
        task.stagnant_attempts = 0
        self.state.current += 1
        self._save_state()
        self.ui.set("任務完成", task.title)
        show_todo(self.state, self.ui)

    def _execute_current_task(self, task: Task) -> str:
        strategy_note = ""
        if task.stagnant_attempts >= NO_PROGRESS_LIMIT:
            strategy_note = (
                "Previous attempts made no effective progress. "
                "Reinspect the project, identify the blocking assumption, "
                "and use a different implementation approach. "
                "Do not repeat the same actions."
            )

        def call() -> str:
            output, changed = protected_ask(
                self.agent,
                execution_prompt(
                    self.state,
                    self.root,
                    self.protected,
                    strategy_note,
                ),
                self.protected,
            )
            if changed:
                raise RunnerError(
                    "protected file modified and restored: "
                    + ", ".join(changed)
                )
            return output

        return retry_model_call(
            call,
            self.ui,
            "AI 正在處理目前任務",
            f"{task.id} · {task.title} · attempt {task.attempts}",
            self.args.retry_wait,
            self.args.retry_max_wait,
        )

    def _review_current_task(
        self,
        task: Task,
        output: str,
    ) -> dict[str, Any]:
        def call() -> dict[str, Any]:
            raw, protected_changed, project_changed = readonly_ask(
                self.agent,
                review_prompt(
                    self.state,
                    self.root,
                    self.protected,
                    output,
                ),
                self.root,
                self.work,
                self.protected,
            )
            changed = [*protected_changed, *project_changed]
            if changed:
                raise RunnerError(
                    "review modified files and they were restored: "
                    + ", ".join(changed)
                )
            return parse_review(raw)

        return retry_model_call(
            call,
            self.ui,
            "AI 正在確認任務是否完成",
            task.title,
            self.args.retry_wait,
            self.args.retry_max_wait,
        )

    def _validate_cycle(self) -> int | None:
        detail = (
            "AI · new session"
            if self.ai_validation
            else self.validator.name
        )
        self.ui.start("正在執行最終驗證", detail)
        try:
            passed, output = self._run_validator()
        except RunnerError as error:
            passed, output = False, str(error)
        finally:
            self.ui.stop()

        self.state.validator_output = output[-MAX_VALIDATOR_OUTPUT_CHARS:]
        if passed:
            self.state.completed = True
            self._save_state()
            self.ui.set("全部完成", "Validator PASS")
            return 0

        self.state.cycle += 1
        self.state.current = len(self.state.tasks)
        self._save_state()
        validator_name = (
            "AI FAIL"
            if self.ai_validation
            else "file validator FAIL"
        )
        self.ui.set(
            "最終驗證失敗，保留修改並重新拆分",
            validator_name,
        )
        show_todo(self.state, self.ui)
        if (
            self.args.max_cycles
            and self.state.cycle > self.args.max_cycles
        ):
            return 3
        return None

    def _run_validator(self) -> tuple[bool, str]:
        if self.ai_validation:
            return run_ai_validator(
                self.args,
                self.root,
                self.work,
                self.state,
                self.protected,
                self.ui,
            )

        assert self.validator is not None
        return run_file_validator(
            self.validator,
            self.root,
            self.state_file,
            self.args.validator_timeout,
            self.args.validator_arg,
            self.protected,
        )


def execute(args: argparse.Namespace) -> int:
    return TaskRunner(args).run()
