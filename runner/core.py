"""Core task execution flow shared by every AI backend."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .agent import AgentClient
from .agent_args import (
    runtime_agent_args,
)
from .errors import RunnerError, diagnostic_error
from .models import RunState, Task
from .planning import build_plan
from .reviewing import review_task, skipped_review
from .policy import protected_paths as policy_protected_paths
from .prompting import (
    bounded_text,
    execution_prompt,
    should_refresh_goal,
    render_prompt_template,
)
from .ui import LiveUI, show_todo
from .support import (
    MAX_TASK_OUTPUT_CHARS,
    MAX_VALIDATOR_OUTPUT_CHARS,
    NO_PROGRESS_LIMIT,
    changed_project_files,
    cleanup_stale_artifacts,
    project_fingerprint,
    project_manifest,
    protected_ask,
    progress_key,
    retry_model_call,
    run_file_validator,
    normalize_protected_paths,
    runner_source_files,
    write_json,
)
from .validation import run_ai_validator
from .backends.qwen import update_qwen_goal_reference
from .script_runner import (
    execute_script as execute_yaml_script,
)


MODEL_CALL_ERRORS_BEFORE_TASK_RETRY = 3
EXECUTION_MODEL_ERRORS_BEFORE_TASK_FLOW = 1
VALIDATOR_REPAIR_AFTER_SAME_FAILURES = 2


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
        self.state_backup_file = self._state_backup_file()

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
            debug_dir=self.work / "debug",
        )
        self.backend_files = self.agent.prepare_project()
        if args.backend == "qwen":
            update_qwen_goal_reference(self.root, getattr(args, "goal_file", None))
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
            log_path=self.work / "log.txt",
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
            if self.args.plan_only:
                self.ui.set("Plan ready", "plan-only stopped before execution")
                return 0
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
        goal_file = getattr(self.args, "goal_file", None)
        paths = [
            *([Path(goal_file).resolve()] if goal_file else []),
            *([self.validator] if self.validator else []),
            self.state_file,
            *runner_source_files(),
            *self.backend_files,
            *policy_protected_paths(self.root),
            *[Path(value).resolve() for value in self.args.protect_file],
        ]
        return normalize_protected_paths(paths)

    def _load_or_create_state(self) -> RunState:
        if self.args.resume:
            self._restore_state_backup()
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
            state.validator_output = bounded_text(
                state.validator_output,
                MAX_VALIDATOR_OUTPUT_CHARS,
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
        data = self.state.dump()
        write_json(self.state_file, data)
        write_json(self.state_backup_file, data)

    def _state_backup_file(self) -> Path:
        key = hashlib.sha256(str(self.work).lower().encode("utf-8")).hexdigest()[:24]
        return Path(tempfile.gettempdir()) / "ai-task-runner-state" / key / "state.json"

    def _restore_state_backup(self) -> None:
        if not self.state_backup_file.is_file():
            return
        try:
            payload = json.loads(self.state_backup_file.read_text(encoding="utf-8"))
            state = RunState.load(payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        if Path(state.project_root).resolve() != self.root:
            return
        write_json(self.state_file, payload)

    def _save_session(self) -> None:
        self.state.agent_session_id = self.agent.session_id
        self._save_state()

    def _plan_if_needed(self) -> None:
        if not self._needs_planning():
            return

        self._set_stage("planning")
        planned = retry_model_call(
            lambda: build_plan(
                self.args,
                self.root,
                self.work,
                self.state,
                self.protected,
                self.ui,
                self.agent,
            ),
            self.ui,
            "AI 正在規劃並拆分任務",
            "",
            self.args.retry_wait,
            self.args.retry_max_wait,
        )
        self.state.agent_session_id = self.agent.session_id
        self.state.tasks = planned
        self.state.current = 0
        self._save_state()
        show_todo(self.state, self.ui)

    def _needs_planning(self) -> bool:
        if self.state.tasks and self.state.current < len(self.state.tasks):
            return False
        if self.state.stage == "validator_failed":
            return True
        return not (
            self.state.tasks
            and self.state.current >= len(self.state.tasks)
            and all(task.status == "completed" for task in self.state.tasks)
        )

    def _run_pending_tasks(self) -> int | None:
        while self.state.current < len(self.state.tasks):
            task = self.state.tasks[self.state.current]
            task.attempts += 1
            self._save_state()
            show_todo(self.state, self.ui)

            project_before = project_manifest(self.root, self.work)
            try:
                self._set_stage("executing")
                output = self._execute_current_task(task)
                task.last_output = output[-MAX_TASK_OUTPUT_CHARS:]
                self._save_session()

                changed_files = changed_project_files(self.root, self.work, project_before)
                task.changed_files = list(dict.fromkeys([*task.changed_files, *changed_files]))
                self._save_state()
                if task.changed_files:
                    self._set_stage("reviewing")
                    review = self._review_current_task(task, output)
                else:
                    self.ui.set(
                        "沒有專案變更，略過 Review",
                        f"{task.title} · final validator will decide",
                    )
                    review = skipped_review("No project changes; final validator will decide")
            except RunnerError as error:
                result = self._handle_execution_error(
                    task,
                    error,
                    project_before,
                )
                if result is not None:
                    return result
                continue

            result = self._handle_review_result(task, review)
            if result is not None:
                return result
            continue
        return None

    def _handle_execution_error(
        self,
        task: Task,
        error: RunnerError,
        project_before: dict[str, tuple[str, str | None]],
    ) -> int | None:
        changed_files = changed_project_files(self.root, self.work, project_before)
        changed = bool(changed_files)
        task.changed_files = list(dict.fromkeys([*task.changed_files, *changed_files]))
        task.last_output = (
            "Previous model call failed before task completion"
            + (" after changing project files" if changed else "")
            + ":\n"
            + str(error)[-MAX_TASK_OUTPUT_CHARS:]
        )
        task.status = "pending"
        if changed:
            task.progress_key = ""
            task.stagnant_attempts = 0
        else:
            lines = [line.strip() for line in str(error).splitlines() if line.strip()]
            signature = lines[-1] if lines else type(error).__name__
            key = hashlib.sha256(signature.encode("utf-8")).hexdigest()
            if key == task.progress_key:
                task.stagnant_attempts += 1
            else:
                task.progress_key = key
                task.stagnant_attempts = 1
        self.state.agent_session_id = self.agent.session_id
        self._save_state()
        shown_files = changed_files[:20]
        changed_detail = ",".join(shown_files) if shown_files else "-"
        if len(changed_files) > len(shown_files):
            changed_detail += f",...(+{len(changed_files) - len(shown_files)})"
        details = [
            f"session={self.agent.session_id or '-'}",
            f"changed_files={len(changed_files)}:{changed_detail}",
            f"task_changed_files={len(task.changed_files)}",
        ]
        cause = diagnostic_error(error)
        if cause is not None:
            return_code = getattr(cause, "return_code", None)
            elapsed = getattr(cause, "elapsed", 0.0)
            if return_code is not None:
                details.append(f"exit_code={return_code}")
            if elapsed:
                details.append(f"elapsed_seconds={elapsed:.1f}")
            command_mode = getattr(cause, "command_mode", "")
            if command_mode:
                details.append(f"command_mode={command_mode}")
            source_event = getattr(cause, "session_source_event", "")
            if source_event:
                details.append(f"session_source_event={source_event}")
            output = getattr(cause, "output", "")
            if output:
                tail = " ".join(str(output).split())[-1000:]
                details.append(f"stderr_tail={tail}")
        details.append(str(error)[-1000:])
        self.ui.set(
            "模型階段失敗，準備重試任務",
            " | ".join(details),
        )
        if changed:
            self.ui.set(
                "Executor 異常但已有檔案變更，先執行 Review",
                task.title,
            )
            self._save_session()
            self._set_stage("reviewing")
            review = self._review_current_task(task, task.last_output)
            return self._handle_review_result(task, review)

        self._save_session()
        self._rebuild_stagnant_session(task)
        self._set_stage("task_retry_wait", str(error))
        return self._prepare_task_retry(task)

    def _handle_review_result(
        self,
        task: Task,
        review: dict[str, Any],
    ) -> int | None:
        task.last_review = review
        self._save_session()
        if review["completed"] is True:
            task.review_skipped = bool(review.get("review_skipped"))
            task.review_skip_reason = str(review.get("reason", "")) if task.review_skipped else ""
            self._complete_current_task(task)
            return None

        task.status = "pending"
        self._record_no_progress(task, review)
        self._rebuild_stagnant_session(task)
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

    def _rebuild_stagnant_session(self, task: Task) -> None:
        if task.stagnant_attempts < NO_PROGRESS_LIMIT:
            return
        self.agent.session_id = ""
        self.state.agent_session_id = ""
        task.progress_key = ""
        task.stagnant_attempts = 0
        task.last_output = bounded_text(
            task.last_output
            + "\nRecovery: Previous attempts made no effective progress. "
              "Continue this TODO with a different approach in the rebuilt session.",
            MAX_TASK_OUTPUT_CHARS,
        )
        self.ui.set(
            "目前 session 持續無進展，下一次改用 fresh session",
            task.title,
        )

    def _complete_current_task(self, task: Task) -> None:
        task.status = "completed"
        task.last_output = ""
        task.progress_key = ""
        task.stagnant_attempts = 0
        self.state.agent_session_id = self.agent.session_id
        self.state.current += 1
        self._save_state()
        self.ui.set("任務完成", task.title)
        show_todo(self.state, self.ui)

    def _validator_repair_hint(self) -> str:
        if not self.state.validator_output.strip():
            return ""
        repeat_hint = ""
        if self.state.validator_failure_count >= VALIDATOR_REPAIR_AFTER_SAME_FAILURES:
            repeat_hint = render_prompt_template(
                "validator_repair_repeat_hint.md",
                {"failure_count": self.state.validator_failure_count},
            )
        return render_prompt_template(
            "validator_repair_hint.md",
            {"repeat_hint": repeat_hint},
        )

    def _execute_current_task(self, task: Task) -> str:
        change_detected = self._project_change_detector()

        def call() -> str:
            output, changed = protected_ask(
                self.agent,
                execution_prompt(
                    self.state,
                    self.root,
                    self.protected,
                    self._validator_repair_hint(),
                    str(self.validator) if self.validator else "",
                    should_refresh_goal(self.state, bool(self.agent.session_id)),
                    task.attempts > 1 and not bool(self.agent.session_id),
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
        review = review_task(
            self.args,
            self.root,
            self.work,
            self.state,
            self.protected,
            self.ui,
            task,
            output,
        )
        if review.get("review_skipped"):
            task.review_skip_reason = str(review.get("reason", ""))
            self._save_state()
        return review

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
            output = str(error)
            self.state.validator_output = bounded_text(
                output, MAX_VALIDATOR_OUTPUT_CHARS
            )
            self._set_stage("validator_retry_wait", output)
            self.ui.set("Validator 無法執行，稍後重試", output[-1000:])
            if self.args.retry_delay:
                time.sleep(self.args.retry_delay)
            return None
        finally:
            self.ui.stop()

        self.state.validator_output = bounded_text(output, MAX_VALIDATOR_OUTPUT_CHARS)
        if passed:
            self.state.validator_failure_key = ""
            self.state.validator_failure_count = 0
            self.agent.session_id = ""
            self.state.agent_session_id = ""
            self.state.completed = True
            self._set_stage("completed")
            self._save_state()
            self.ui.set("全部完成", "Validator PASS")
            return 0

        self._record_validator_failure(output)
        if self.state.validator_failure_count >= VALIDATOR_REPAIR_AFTER_SAME_FAILURES:
            self.agent.session_id = ""
            self.state.agent_session_id = ""
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
                runtime_agent_args(self.args.backend, self.args.agent_arg),
                MODEL_CALL_ERRORS_BEFORE_TASK_RETRY,
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
    if args.script:
        return execute_script(args)
    return TaskRunner(args).run()


def execute_script(args: argparse.Namespace) -> int:
    """Compatibility wrapper for callers that import script mode directly."""
    return execute_yaml_script(args, execute)
