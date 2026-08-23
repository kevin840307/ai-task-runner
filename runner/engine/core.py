"""Core task execution flow shared by every AI backend."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from ..config.defaults import (
    MAX_TASK_OUTPUT_CHARS,
    MAX_VALIDATOR_OUTPUT_CHARS,
    REPAIR_FULL_PLAN_AFTER_SAME_FAILURES,
)

from ..agent.calls import retry_model_call
from ..agent.factory import AgentFactory
from ..agent.prompts import (
    bounded_text,
    execution_prompt,
    render_prompt_template,
    should_refresh_goal,
)
from ..config import RuntimeConfig
from ..errors import ConfigurationError, RunnerError, backend_diagnostic_parts
from .models import ReviewResult, RunStage, Task
from ..safety.policy import protected_paths as policy_protected_paths
from ..safety.project_guard import (
    changed_project_files,
    cleanup_stale_artifacts,
    normalize_protected_paths,
    project_fingerprint,
    project_manifest,
    protected_ask,
    runner_source_files,
)
from ..app.script_runner import execute_script as execute_yaml_script
from .state_store import StateStore
from .recovery import (
    Outcome,
    Transition,
    decide,
    escalate_task_recovery,
    record_execution_progress,
    record_review_progress,
    validator_failure_key,
)
from .transitions import (
    complete_run,
    complete_task,
    install_plan,
    prepare_repair_cycle,
    prepare_task_replan,
    set_stage,
)
from ..app.ui import LiveUI, show_todo
from ..workflow.planning import build_plan
from ..workflow.reviewing import review_task
from ..workflow.validation.ai import run_ai_validator
from ..workflow.validation.file import run_file_validator

MODEL_CALL_ERRORS_BEFORE_TASK_RETRY = 3
EXECUTION_MODEL_ERRORS_BEFORE_TASK_FLOW = 1


class TaskRunner:
    """Owns one goal, one main model session, and one state file."""

    def __init__(self, args: RuntimeConfig | argparse.Namespace) -> None:
        if not isinstance(args, RuntimeConfig):
            args = RuntimeConfig.from_namespace(args)
        self.args = args
        if not args.validator:
            raise RunnerError("--validator is required unless --script is used")
        self.root = Path(args.project_root).resolve()
        self.ai_validation = args.validator.lower() == "ai"
        self.validator = (
            None
            if self.ai_validation
            else Path(args.validator).resolve()
        )
        self.work = self.root / args.work_dir
        self.state_store = StateStore(self.root, self.work)
        self.state_file = self.state_store.path

        self._validate_paths()
        cleanup_stale_artifacts(self.work)
        self.state = self.state_store.load_or_create(
            args.goal,
            resume=args.resume,
            force_new=args.force_new,
        )
        self.agent_factory = AgentFactory(
            args,
            self.root,
            self.work / "debug",
        )
        self.agent = self.agent_factory.create(
            "runtime",
            session_id=self.state.agent_session_id,
            timeout=args.agent_timeout,
        )
        self.backend_files = self.agent.prepare_project()
        self.agent.update_goal_reference(args.goal_file)
        if not args.resume:
            self._save_state()
        self.protected = self._build_protected_files()
        context = {
            "script_index": args.script_index,
            "script_total": args.script_total,
        }
        self.ui = LiveUI(
            event_callback=args.event_callback,
            json_events=args.json_events,
            human_output=args.human_output,
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
                self.ui.set("Plan ready", "plan-only completed without execution")
                return 0
            self._run_pending_tasks()
            if self._needs_planning():
                continue
            self._validate_cycle()
        return 0

    def _set_stage(self, stage: RunStage, detail: str = "") -> None:
        set_stage(self.state, stage, detail)
        self._save_state()


    def _validate_paths(self) -> None:
        if not self.root.is_dir():
            raise RunnerError("invalid project root or validator")
        if self.validator is not None and not self.validator.is_file():
            raise RunnerError("invalid project root or validator")

    def _build_protected_files(self) -> list[Path]:
        goal_file = getattr(self.args, "goal_file", None)
        ai_prompt_file = getattr(self.args, "ai_validator_prompt_file", None)
        paths = [
            *([Path(goal_file).resolve()] if goal_file else []),
            *([Path(ai_prompt_file).resolve()] if ai_prompt_file else []),
            *([self.validator] if self.validator else []),
            self.state_file,
            *runner_source_files(),
            *self.backend_files,
            *policy_protected_paths(self.root),
            *[Path(value).resolve() for value in self.args.protect_file],
        ]
        return normalize_protected_paths(paths)

    def _save_state(self) -> None:
        self.state_store.save(self.state)

    def _save_session(self) -> None:
        self.state.agent_session_id = self.agent.session_id
        self._save_state()

    def _plan_if_needed(self) -> None:
        if not self._needs_planning():
            return

        self._set_stage("planning")
        agent_factory = getattr(self, "agent_factory", None) or AgentFactory(
            self.args,
            self.root,
            self.work / "debug",
        )
        agent_factory.configure(
            self.agent,
            "planning",
            allow_project_read=True,
        )
        try:
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
        finally:
            agent_factory.configure(self.agent, "runtime")
        install_plan(self.state, planned, self.agent.session_id)
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

    def _run_pending_tasks(self) -> None:
        while self.state.current < len(self.state.tasks):
            task = self.state.tasks[self.state.current]
            task.attempts += 1
            self._save_state()
            show_todo(self.state, self.ui)

            outcome = self._run_task(task)
            transition = decide(
                outcome,
                task=task,
                threshold=self.args.task_recovery_threshold,
            )

            if transition.action == "advance":
                self._complete_current_task(task)
                continue
            if transition.action == "replan":
                self._replan_stuck_task(task, transition.reason)
                return
            self._prepare_task_retry(
                task,
                transition.retry_session,
                transition.reason,
            )

    def _run_task(self, task: Task) -> Outcome:
        """Run one TODO through Execute -> Review and return one stage-neutral outcome."""
        execution = self._execute_outcome(task)
        execution_transition = decide(
            execution,
            task=task,
            threshold=self.args.task_recovery_threshold,
        )
        if execution.error is not None:
            self._log_execution_outcome(task, execution, execution_transition)
        if execution_transition.action != "advance":
            return execution

        self._set_stage("reviewing")
        if execution.status == "error":
            self.ui.set(
                "Executor 異常但已有檔案變更，先執行 Review",
                task.title,
            )
        review = self._review_current_task(task, task.last_output)
        task.last_review = review
        self._save_session()
        outcome = Outcome(
            "review",
            "pass" if review["completed"] else "fail",
            output=str(review.get("reason", "")),
            feedback=list(review["missing_items"]),
            skipped=bool(review.get("review_skipped")),
        )

        if outcome.status == "pass":
            task.review_skipped = outcome.skipped
            task.review_skip_reason = outcome.output if outcome.skipped else ""
            return outcome

        task.status = "pending"
        record_review_progress(task, self.root, self.work, outcome.feedback)
        self._save_state()
        self.ui.set("任務未完成，準備恢復", outcome.output)
        return outcome

    def _execute_outcome(self, task: Task) -> Outcome:
        project_before = project_manifest(self.root, self.work)
        self._set_stage("executing")
        try:
            output = self._execute_current_task(task)
            error = None
        except ConfigurationError:
            raise
        except RunnerError as current:
            output = ""
            error = current

        changed_files = changed_project_files(self.root, self.work, project_before)
        outcome = Outcome(
            "execute",
            "pass" if error is None else "error",
            output=output,
            error=error,
            changed_files=changed_files,
        )
        task.changed_files = list(dict.fromkeys([*task.changed_files, *changed_files]))
        if error is None:
            task.last_output = output[-MAX_TASK_OUTPUT_CHARS:]
        else:
            task.status = "pending"
            task.last_output = (
                "Previous model call failed before task completion"
                + (" after changing project files" if changed_files else "")
                + ":\n"
                + str(error)[-MAX_TASK_OUTPUT_CHARS:]
            )
            record_execution_progress(task, error, bool(changed_files))
        self._save_session()
        return outcome

    def _log_execution_outcome(
        self,
        task: Task,
        outcome: Outcome,
        transition: Transition,
    ) -> None:
        assert outcome.error is not None
        shown_files = outcome.changed_files[:20]
        changed_detail = ",".join(shown_files) if shown_files else "-"
        if len(outcome.changed_files) > len(shown_files):
            changed_detail += f",...(+{len(outcome.changed_files) - len(shown_files)})"
        details = [
            f"outcome={outcome.status}",
            f"session={self.agent.session_id or '-'}",
            f"changed_files={len(outcome.changed_files)}:{changed_detail}",
            f"task_changed_files={len(task.changed_files)}",
            f"stagnant_attempts={task.stagnant_attempts}",
            f"failure_signature={task.progress_key[:12] or '-'}",
            f"task_recovery_action={transition.action}",
            f"retry_session={transition.retry_session}",
        ]
        details.extend(backend_diagnostic_parts(outcome.error, include_output=True))
        details.append(str(outcome.error)[-1000:])
        self.ui.set("模型階段失敗，套用統一恢復策略", " | ".join(details))

    def _prepare_task_retry(
        self,
        task: Task,
        retry_session: str = "same",
        reason: str = "",
    ) -> None:
        if retry_session == "fresh":
            self.agent.session_id = ""
            self.state.agent_session_id = ""
            escalate_task_recovery(task)
            task.last_output = bounded_text(
                task.last_output
                + "\nRecovery: The previous session made insufficient progress. "
                  "Continue this TODO with a different approach in a fresh session.",
                MAX_TASK_OUTPUT_CHARS,
            )
            self.ui.set("恢復策略升級：改用 fresh session", task.title)
        self._set_stage("task_retry_wait", reason)
        self._save_state()
        show_todo(self.state, self.ui)
        if self.args.retry_delay:
            time.sleep(self.args.retry_delay)

    def _replan_stuck_task(self, task: Task, reason: str) -> None:
        feedback = bounded_text(
            f"Previous plan stalled on TODO {task.id} ({task.title}). "
            f"Recovery reason: {reason}. Latest evidence: {task.last_output}",
            MAX_TASK_OUTPUT_CHARS,
        )
        self.agent.session_id = ""
        prepare_task_replan(self.state, feedback)
        self._save_state()
        self.ui.set("目前 TODO 持續無法推進，保留成果並重新規劃", task.title)

    def _complete_current_task(self, task: Task) -> None:
        complete_task(self.state, task, self.agent.session_id)
        self._save_state()
        self.ui.set("任務完成", task.title)

    def _validator_repair_hint(self) -> str:
        if not self.state.validator_output.strip():
            return ""
        repeat_hint = ""
        if self.state.validator_failure_count >= REPAIR_FULL_PLAN_AFTER_SAME_FAILURES:
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
                    should_refresh_goal(bool(self.agent.session_id)),
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
            max_attempts=1,
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
    ) -> ReviewResult:
        review = review_task(
            self.args,
            self.root,
            self.work,
            self.state,
            self.protected,
            self.ui,
            task,
            output,
            getattr(self, "agent_factory", None),
        )
        if review.get("review_skipped"):
            task.review_skip_reason = str(review.get("reason", ""))
            self._save_state()
        return review

    def _validate_cycle(self) -> None:
        detail = (
            "AI · new session"
            if self.ai_validation
            else self.validator.name
            + (
                " + AI vote"
                if getattr(self.args, "ai_validator_prompt", "").strip()
                else ""
            )
        )
        self._set_stage("validating")
        self.ui.start("正在執行最終驗證", detail)
        try:
            try:
                passed, output = self._run_validator()
                outcome = Outcome(
                    "validate", "pass" if passed else "fail", output=output
                )
            except RunnerError as error:
                outcome = Outcome(
                    "validate", "error", output=str(error), error=error
                )
        finally:
            self.ui.stop()

        self.state.validator_output = bounded_text(
            outcome.output, MAX_VALIDATOR_OUTPUT_CHARS
        )
        transition = decide(outcome)

        if transition.action == "retry":
            self._set_stage("validator_retry_wait", outcome.output)
            self.ui.set("Validator 無法執行，稍後重試", outcome.output[-1000:])
            if self.args.retry_delay:
                time.sleep(self.args.retry_delay)
            return

        if transition.action == "advance":
            self.agent.session_id = ""
            complete_run(self.state)
            self._set_stage("completed")
            self._save_state()
            self.ui.set("全部完成", "Validator PASS")
            return

        self._record_validator_failure(outcome.output)
        full_replan = (
            self.state.validator_failure_count >= REPAIR_FULL_PLAN_AFTER_SAME_FAILURES
            or bool(self.args.full_replan_threshold and self.state.cycle >= self.args.full_replan_threshold)
        )
        if full_replan:
            self.agent.session_id = ""
            self.state.agent_session_id = ""
        prepare_repair_cycle(self.state, full_replan=full_replan)
        self._save_state()
        validator_name = (
            "AI FAIL"
            if self.ai_validation
            else "AI vote FAIL"
            if outcome.output.startswith("FILE_VALIDATION_PASS\n")
            else "file validator FAIL"
        )
        self.ui.set(
            "最終驗證失敗，保留修改並重新拆分",
            validator_name,
        )
        show_todo(self.state, self.ui)

    def _record_validator_failure(self, output: str) -> None:
        key = validator_failure_key(output)
        if key == self.state.validator_failure_key:
            self.state.validator_failure_count += 1
        else:
            self.state.validator_failure_key = key
            self.state.validator_failure_count = 1
        self._set_stage("validator_failed", output)

    def _run_validator(self) -> tuple[bool, str]:
        if self.ai_validation:
            ai_prompt = (
                getattr(self.args, "ai_validator_prompt", "").strip()
                or self.args.validator_prompt
            )
            return run_ai_validator(
                self.args,
                self.root,
                self.work,
                self.state,
                self.protected,
                self.ui,
                MODEL_CALL_ERRORS_BEFORE_TASK_RETRY,
                ai_prompt,
                agent_factory=getattr(self, "agent_factory", None),
            )

        assert self.validator is not None
        passed, output = run_file_validator(
            self.validator,
            self.root,
            self.state_file,
            self.args.validator_timeout,
            self.args.validator_arg,
            self.protected,
        )
        ai_prompt = getattr(self.args, "ai_validator_prompt", "")
        if not passed or not ai_prompt.strip():
            return passed, output
        ai_passed, ai_output = run_ai_validator(
            self.args,
            self.root,
            self.work,
            self.state,
            self.protected,
            self.ui,
            MODEL_CALL_ERRORS_BEFORE_TASK_RETRY,
            ai_prompt,
            agent_factory=getattr(self, "agent_factory", None),
        )
        return ai_passed, "FILE_VALIDATION_PASS\n" + ai_output


def execute(args: RuntimeConfig | argparse.Namespace) -> int:
    if not isinstance(args, RuntimeConfig):
        args = RuntimeConfig.from_namespace(args)
    if args.script:
        return execute_script(args)
    return TaskRunner(args).run()


def execute_script(args: RuntimeConfig) -> int:
    """Compatibility wrapper for callers that import script mode directly."""
    return execute_yaml_script(args, execute)
