"""Core task execution flow shared by every AI backend."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
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
    format_validator_feedback,
    parse_ai_validation,
    parse_review,
    parse_tasks,
    plan_prompt,
    project_fingerprint,
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


QWEN_COMPUTER_USE_TOOLS = (
    "computer_use__bring_to_front",
    "computer_use__check_for_update",
    "computer_use__check_permissions",
    "computer_use__launch_app",
    "computer_use__kill_app",
    "computer_use__hotkey",
    "computer_use__list_apps",
    "computer_use__list_windows",
    "computer_use__get_accessibility_tree",
    "computer_use__get_agent_cursor_state",
    "computer_use__get_config",
    "computer_use__get_cursor_position",
    "computer_use__get_recording_state",
    "computer_use__get_screen_size",
    "computer_use__get_window_state",
    "computer_use__screenshot",
    "computer_use__click",
    "computer_use__double_click",
    "computer_use__right_click",
    "computer_use__press_key",
    "computer_use__type_text",
    "computer_use__scroll",
    "computer_use__move_cursor",
    "computer_use__drag",
    "computer_use__page",
    "computer_use__replay_trajectory",
    "computer_use__set_agent_cursor_enabled",
    "computer_use__set_agent_cursor_motion",
    "computer_use__set_agent_cursor_style",
    "computer_use__set_config",
    "computer_use__set_value",
    "computer_use__start_recording",
    "computer_use__stop_recording",
    "computer_use__end_session",
    "computer_use__start_session",
    "computer_use__zoom",
    "bring_to_front",
    "check_for_update",
    "check_permissions",
    "launch_app",
    "kill_app",
    "hotkey",
    "list_apps",
    "list_windows",
    "get_accessibility_tree",
    "get_agent_cursor_state",
    "get_config",
    "get_cursor_position",
    "get_recording_state",
    "get_screen_size",
    "get_window_state",
    "screenshot",
    "click",
    "double_click",
    "right_click",
    "press_key",
    "type_text",
    "scroll",
    "move_cursor",
    "drag",
    "page",
    "replay_trajectory",
    "set_agent_cursor_enabled",
    "set_agent_cursor_motion",
    "set_agent_cursor_style",
    "set_config",
    "set_value",
    "start_recording",
    "stop_recording",
    "end_session",
    "start_session",
    "zoom",
)

QWEN_PLANNING_EXCLUDED_TOOLS = (
    "read_file",
    "read_mcp_resource",
    "list_directory",
    "glob",
    "grep_search",
    "write_file",
    "edit",
    "notebook_edit",
    "run_shell_command",
    "tool_search",
    "todo_write",
    "skill",
    "agent",
    *QWEN_COMPUTER_USE_TOOLS,
)
QWEN_RUNTIME_EXCLUDED_TOOLS = (
    "todo_write",
    "skill",
    "agent",
    *QWEN_COMPUTER_USE_TOOLS,
)
MODEL_CALL_ERRORS_BEFORE_TASK_RETRY = 3
EXECUTION_MODEL_ERRORS_BEFORE_TASK_FLOW = 1
VALIDATOR_REPAIR_AFTER_SAME_FAILURES = 2


def planning_agent_args(backend: str, extra_args: Sequence[str]) -> list[str]:
    """Preserve Qwen planning permissions while trimming custom context load."""
    result = list(extra_args)
    if backend == "qwen":
        ensure_qwen_yolo(result)
        exclude_qwen_tools(result, QWEN_PLANNING_EXCLUDED_TOOLS)
    return result


def runtime_agent_args(backend: str, extra_args: Sequence[str]) -> list[str]:
    result = list(extra_args)
    if backend == "qwen":
        ensure_qwen_yolo(result)
        exclude_qwen_tools(result, QWEN_RUNTIME_EXCLUDED_TOOLS)
    return result


def ensure_qwen_yolo(args: list[str]) -> None:
    if "--yolo" not in args and "--approval-mode" not in args:
        args.append("--yolo")


def exclude_qwen_tools(args: list[str], tool_names: Sequence[str]) -> None:
    for tool_name in tool_names:
        if tool_name not in args:
            args.extend(["--exclude-tools", tool_name])


def repair_review_needs_project_change(
    state: RunState,
    task: Task,
    review: dict[str, Any],
    project_changed: bool,
) -> bool:
    return (
        bool(state.validator_output.strip())
        and task.title == "Repair validator failure"
        and review.get("completed") is True
        and not project_changed
    )


def planning_agent_root(backend: str, root: Path, work: Path) -> Path:
    """Let Qwen write planning artifacts without making source files its cwd."""
    return work if backend == "qwen" else root


def derive_tasks_from_goal(
    goal: str,
    cycle: int,
    validator_feedback: str = "",
) -> list[Task]:
    feedback = validator_feedback.strip()
    if feedback:
        repair_feedback = format_validator_feedback(feedback, 2000)
        return [
            Task(
                id=f"c{cycle:02d}-t001",
                title="Repair validator failure",
                description=(
                    "Make the smallest maintainable project change needed "
                    "to satisfy the goal and address this validator feedback:\n"
                    f"{repair_feedback}"
                ),
                acceptance_criteria=[
                    "The validator feedback is addressed",
                    "The requested behavior is implemented",
                    "Relevant validator checks pass",
                ],
            )
        ]
    deliverables = numbered_goal_items(goal)
    if len(deliverables) < 2:
        deliverables = deliverable_goal_items(goal)
    if len(deliverables) >= 2:
        return [
            Task(
                id=f"c{cycle:02d}-t{index:03d}",
                title=short_task_title(item),
                description=item,
                acceptance_criteria=[
                    "This deliverable is implemented",
                    "Relevant validator checks pass",
                ],
            )
            for index, item in enumerate(deliverables, 1)
        ]
    return [
        Task(
            id=f"c{cycle:02d}-t001",
            title="Implement requested change",
            description=(
                "Make the smallest maintainable project change needed "
                f"to satisfy the goal: {goal}"
            ),
            acceptance_criteria=[
                "The requested behavior is implemented",
                "Relevant validator checks pass",
            ],
        )
    ]


def right_size_planned_tasks(
    goal: str,
    cycle: int,
    planned: list[Task],
    validator_feedback: str = "",
) -> list[Task]:
    """Use deterministic splitting when the planner under-splits deliverables."""
    if validator_feedback.strip():
        return planned
    fallback = derive_tasks_from_goal(goal, cycle)
    return fallback if len(fallback) > len(planned) else planned


def numbered_goal_items(goal: str) -> list[str]:
    items: list[str] = []
    for line in goal.splitlines():
        match = re.match(r"^\s*\d+[\).]\s+(.+?)\s*$", line)
        if match:
            items.append(match.group(1))
    return items


def deliverable_goal_items(goal: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n", goal) if part.strip()]
    items: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not looks_like_deliverable(part):
            continue
        normalized = " ".join(part.split())
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(normalized)
    concrete = [item for item in items if not looks_like_overview(item)]
    return concrete if len(concrete) >= 2 else items


def looks_like_deliverable(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered.startswith(("do not ask", "don't ask", "expected command")):
        return False
    if re.search(r"\b[\w.-]+\.(?:py|js|ts|json|md|csv|txt|ya?ml|toml|ini)\b", text):
        return True
    return bool(
        re.search(
            r"\b(?:cli|command|tool|output|report|document|readme|validator|test|"
            r"export|store|stored|storing|persist|persistence|generate|produce|"
            r"support|data format|fields?)\b",
            text,
            re.IGNORECASE,
        )
    )


def looks_like_overview(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered.startswith(("build ", "create ", "implement ")):
        return False
    has_concrete_file = re.search(
        r"\b[\w.-]+\.(?:py|js|ts|json|md|ya?ml|toml|ini)\b",
        text,
    )
    has_verifiable_action = re.search(
        r"\b(?:produce|generate|export|store|stored|storing|persist|persistence|"
        r"support|document|data format|fields?)\b",
        text,
        re.IGNORECASE,
    )
    return not has_concrete_file and not has_verifiable_action


def short_task_title(text: str, limit: int = 72) -> str:
    title = text.strip().rstrip(".")
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "..."


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
        extra_args=runtime_agent_args(args.backend, args.agent_arg),
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
        MODEL_CALL_ERRORS_BEFORE_TASK_RETRY,
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
            print(json.dumps(event), flush=True)
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
            extra_args=runtime_agent_args(args.backend, args.agent_arg),
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

    def _set_stage(self, stage: str, detail: str = "") -> None:
        now = time.time()
        if self.state.stage != stage:
            self.state.stage = stage
            self.state.stage_started_at = now
        self.state.last_activity_at = now
        self.state.last_error = detail[-1000:] if detail else ""
        self._save_state()

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

        planning_failures = 0
        self._set_stage("planning")

        def plan_call() -> list[Task]:
            nonlocal planning_failures
            planner_root = planning_agent_root(
                self.args.backend,
                self.root,
                self.work,
            )
            planner = AgentClient(
                backend=self.args.backend,
                command=self.args.command,
                root=planner_root,
                extra_args=planning_agent_args(
                    self.args.backend,
                    self.args.agent_arg,
                ),
                session_id="",
                timeout=self.args.planning_timeout,
            )
            planner.prepare_project()
            try:
                output, protected_changed, project_changed = readonly_ask(
                    planner,
                    plan_prompt(
                        self.state.goal,
                        self.root,
                        self.state,
                        self.protected,
                        self.work,
                    ),
                    self.root,
                    self.work,
                    self.protected,
                )
                if protected_changed:
                    raise RunnerError(
                        "AI modified files during planning and they were restored: "
                        + ", ".join(protected_changed)
                    )
                tasks = right_size_planned_tasks(
                    self.state.goal,
                    self.state.cycle,
                    parse_tasks(output, self.state.cycle),
                    self.state.validator_output,
                )
            except RunnerError as error:
                planning_failures += 1
                message = str(error)
                stalled = (
                    "timed out" in message.lower()
                    or "loop detection" in message.lower()
                )
                if (
                    self.args.backend == "qwen"
                    and (stalled or planning_failures >= 3)
                ):
                    self.ui.set(
                        "Qwen planning fallback",
                        "using fallback tasks from the goal after repeated planning failures",
                    )
                    return derive_tasks_from_goal(
                        self.state.goal,
                        self.state.cycle,
                        self.state.validator_output,
                    )
                raise
            if project_changed:
                self.ui.set(
                    "AI restored project changes made during planning",
                    ", ".join(project_changed),
                )
            if planner_root == self.root:
                self.agent.session_id = planner.session_id
            return tasks

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

            project_before = project_fingerprint(self.root, self.work)
            try:
                self._set_stage("executing")
                output = self._execute_current_task(task)
                task.last_output = output[-MAX_TASK_OUTPUT_CHARS:]
                self._save_session()

                self._set_stage("reviewing")
                review = self._review_current_task(task, output)
            except RunnerError as error:
                if project_fingerprint(self.root, self.work) != project_before:
                    try:
                        review = self._review_failed_execution_changes(
                            task,
                            error,
                        )
                    except RunnerError as review_error:
                        if not self.ai_validation:
                            review = self._fallback_review_to_validator(
                                task,
                                review_error,
                            )
                            result = self._handle_review_result(
                                task,
                                review,
                                project_changed=True,
                            )
                            if result is not None:
                                return result
                            continue
                        error = review_error
                    else:
                        result = self._handle_review_result(
                            task,
                            review,
                            project_changed=True,
                        )
                        if result is not None:
                            return result
                        continue

                task.last_output = (
                    "Previous model call failed before task completion:\n"
                    + str(error)[-MAX_TASK_OUTPUT_CHARS:]
                )
                task.status = "pending"
                task.stagnant_attempts += 1
                self.state.agent_session_id = self.agent.session_id
                self._save_state()
                self.ui.set(
                    "模型階段失敗，準備重試任務",
                    str(error)[-500:],
                )
                self._set_stage("task_retry_wait", str(error))
                result = self._prepare_task_retry(task)
                if result is not None:
                    return result
                continue

            result = self._handle_review_result(
                task,
                review,
                project_changed=project_fingerprint(self.root, self.work) != project_before,
            )
            if result is not None:
                return result
            continue
        return None

    def _review_failed_execution_changes(
        self,
        task: Task,
        error: RunnerError,
    ) -> dict[str, Any]:
        output = (
            "Execution model call failed after changing project files; "
            "review the current filesystem state.\n"
            + str(error)[-MAX_TASK_OUTPUT_CHARS:]
        )
        task.last_output = output[-MAX_TASK_OUTPUT_CHARS:]
        self._save_session()
        self.ui.set(
            "模型呼叫失敗但已有專案變更",
            "改由 review 判定目前 task",
        )
        self._set_stage("reviewing")
        return self._review_current_task(task, output)

    def _handle_review_result(
        self,
        task: Task,
        review: dict[str, Any],
        project_changed: bool,
    ) -> int | None:
        if repair_review_needs_project_change(
            self.state,
            task,
            review,
            project_changed,
        ):
            review = {
                "completed": False,
                "reason": (
                    "Validator repair task made no project changes while "
                    "validator feedback is still present."
                ),
                "missing_items": ["Address validator feedback with a project change"],
            }
        task.last_review = review
        self._save_session()
        if review["completed"] is True:
            self._complete_current_task(task)
            return None

        task.status = "pending"
        self._record_no_progress(task, review)
        self._save_state()
        self.ui.set("任務未完成，準備重試", review["reason"])
        return self._prepare_task_retry(task)

    def _prepare_task_retry(self, task: Task) -> int | None:
        show_todo(self.state, self.ui)
        if self.args.max_attempts and task.attempts >= self.args.max_attempts:
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

    def _validator_repair_hint(self) -> str:
        if not self.state.validator_output.strip():
            return ""
        parts = [
            "Validator repair task: reproduce or inspect the first reported "
            "validator failure, then edit the project implementation, "
            "documentation, or output generator that causes it. Do not only "
            "summarize a fix or change runner state."
        ]
        if self.state.validator_failure_count >= VALIDATOR_REPAIR_AFTER_SAME_FAILURES:
            parts.append(
                "Validator repair mode: the final validator has failed with the "
                f"same diagnostic {self.state.validator_failure_count} times. "
                "Treat the validator feedback in Run context as authoritative. "
                "Fix the first reported failure directly, verify the affected files "
                "carefully, and do not dismiss the validator as a false positive "
                "unless there is concrete evidence of an impossible requirement."
            )
        return "\n".join(parts)

    def _fallback_review_to_validator(
        self,
        task: Task,
        error: RunnerError,
    ) -> dict:
        reason = (
            "AI review failed after retries, but project files changed. "
            "Deferring completion judgment to the configured Python final "
            f"validator. Review failure: {str(error)[-500:]}"
        )
        return {"completed": True, "reason": reason, "missing_items": []}

    def _execute_current_task(self, task: Task) -> str:
        strategy_note = ""
        if task.stagnant_attempts >= NO_PROGRESS_LIMIT:
            self.agent.session_id = ""
            strategy_note = (
                "Previous attempts made no effective progress. "
                "Reinspect the project, identify the blocking assumption, "
                "and use a different implementation approach. "
                "A fresh agent session is being used with runner state as "
                "context. Do not repeat the same actions."
            )
        change_detected = self._project_change_detector()

        def call() -> str:
            output, changed = protected_ask(
                self.agent,
                execution_prompt(
                    self.state,
                    self.root,
                    self.protected,
                    "\n".join(
                        part
                        for part in (strategy_note, self._validator_repair_hint())
                        if part
                    ),
                    str(self.validator) if self.validator else "",
                ),
                self.protected,
                self.args.agent_idle_after_change_timeout,
                change_detected,
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
            EXECUTION_MODEL_ERRORS_BEFORE_TASK_FLOW,
        )

    def _project_change_detector(self):
        fingerprint = project_fingerprint(self.root, self.work)

        def changed() -> bool:
            nonlocal fingerprint
            latest = project_fingerprint(self.root, self.work)
            if latest == fingerprint:
                return False
            fingerprint = latest
            return True

        return changed

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
            MODEL_CALL_ERRORS_BEFORE_TASK_RETRY,
        )

    def _validate_cycle(self) -> int | None:
        detail = (
            "AI · new session"
            if self.ai_validation
            else self.validator.name
        )
        self._set_stage("validating")
        self.ui.start("正在執行最終驗證", detail)
        try:
            passed, output = self._run_validator()
        except RunnerError as error:
            passed, output = False, str(error)
        finally:
            self.ui.stop()

        self.state.validator_output = output[-MAX_VALIDATOR_OUTPUT_CHARS:]
        if passed:
            self.state.validator_failure_key = ""
            self.state.validator_failure_count = 0
            self.state.completed = True
            self._set_stage("completed")
            self._save_state()
            self.ui.set("全部完成", "Validator PASS")
            return 0

        self._record_validator_failure(output)
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

    def _record_validator_failure(self, output: str) -> None:
        key = hashlib.sha256(
            "\n".join(line.strip() for line in output.splitlines() if line.strip())
            .encode("utf-8")
        ).hexdigest()
        if key == self.state.validator_failure_key:
            self.state.validator_failure_count += 1
        else:
            self.state.validator_failure_key = key
            self.state.validator_failure_count = 1
        self._set_stage("validator_failed", output)

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
