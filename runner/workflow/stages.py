"""Composable stage blocks; stages return outcomes and never choose the next stage."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..agent import Agent, configure_agent
from ..agent.prompts import bounded_text, execution_prompt, render_prompt_template, should_refresh_goal
from ..agent.retry import retry_model_call
from ..config import RuntimeConfig
from ..config.defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS, REPAIR_FULL_PLAN_AFTER_SAME_FAILURES
from ..engine.models import RunStage, RunState, Task
from ..engine.recovery import Outcome, record_execution_progress, record_review_progress
from ..errors import ConfigurationError, RunnerError
from ..runtime import status as runner_status
from ..runtime.execution import ask as execution_ask
from ..runtime.project_state import changed_project_files, project_fingerprint, project_manifest
from .planning import build_plan
from .reviewing import review_task
from .validation.ai import run_ai_validator
from .validation.file import run_file_validator

MODEL_CALL_ERRORS_BEFORE_TASK_RETRY = 3
EXECUTION_MODEL_ERRORS_BEFORE_TASK_FLOW = 1


@dataclass
class StageContext:
    args: RuntimeConfig
    root: Path
    work: Path
    state: RunState
    agent: Agent
    state_file: Path
    validator: Path | None
    ai_validation: bool
    save_state: Callable[[], None]
    set_stage: Callable[[RunStage, str], None]

    @property
    def task(self) -> Task | None:
        return self.state.tasks[self.state.current] if self.state.current < len(self.state.tasks) else None

    def save_session(self) -> None:
        self.state.agent_session_id = self.agent.session_id
        self.save_state()


class Stage:
    name = "stage"

    def __init__(self, context: StageContext) -> None:
        self.ctx = context

    def run(self, previous: Outcome | None = None) -> Outcome:
        raise NotImplementedError


class PlanningStage(Stage):
    name = "planning"

    def run(self, previous: Outcome | None = None) -> Outcome:
        ctx = self.ctx
        ctx.set_stage("planning", "")
        configure_agent(ctx.agent, ctx.args, "planning", allow_project_read=True)
        try:
            planned = retry_model_call(
                lambda: build_plan(ctx.args, ctx.root, ctx.work, ctx.state, ctx.agent),
                "AI 正在規劃並拆分任務",
                "",
                ctx.args.retry_wait,
                ctx.args.retry_max_wait,
            )
        finally:
            configure_agent(ctx.agent, ctx.args, "runtime")
        return Outcome("planning", "pass", data=planned)


class ExecuteStage(Stage):
    name = "execute"

    def run(self, previous: Outcome | None = None) -> Outcome:
        ctx = self.ctx
        task = ctx.task
        if task is None:
            raise RunnerError("execute stage requires a pending task")
        project_before = project_manifest(ctx.root, ctx.work)
        ctx.set_stage("executing", "")
        try:
            output = self._ask(task)
            error = None
        except ConfigurationError:
            raise
        except RunnerError as current:
            output = ""
            error = current

        changed_files = changed_project_files(ctx.root, ctx.work, project_before)
        task.changed_files = list(dict.fromkeys([*task.changed_files, *changed_files]))
        if error is None:
            task.last_output = output[-MAX_TASK_OUTPUT_CHARS:]
        else:
            task.status = "pending"
            task.last_output = (
                "Previous model call failed before task completion"
                + (" after changing project files" if changed_files else "")
                + ":\n" + str(error)[-MAX_TASK_OUTPUT_CHARS:]
            )
            record_execution_progress(task, error, bool(changed_files))
        ctx.save_session()
        return Outcome(
            "execute", "pass" if error is None else "error",
            output=output, error=error, changed_files=changed_files,
        )

    def _ask(self, task: Task) -> str:
        ctx = self.ctx
        detector = self._change_detector()

        def call() -> str:
            return execution_ask(
                ctx.agent,
                execution_prompt(
                    ctx.state,
                    ctx.root,
                    strategy_note=self._repair_hint(),
                    validator_hint=str(ctx.validator) if ctx.validator else "",
                    include_goal=should_refresh_goal(bool(ctx.agent.session_id)),
                    rebuilt_session=task.attempts > 1 and not bool(ctx.agent.session_id),
                ),
                ctx.root,
                ctx.work,
                mode="write",
                actor="executor",
                idle_timeout=ctx.args.agent_idle_after_change_timeout,
                change_detected=detector,
            )

        return retry_model_call(
            call,
            "AI 正在處理目前任務",
            f"{task.id} · {task.title} · attempt {task.attempts}",
            ctx.args.retry_wait,
            ctx.args.retry_max_wait,
            EXECUTION_MODEL_ERRORS_BEFORE_TASK_FLOW,
            max_attempts=1,
        )

    def _repair_hint(self) -> str:
        state = self.ctx.state
        if not state.validator_output.strip():
            return ""
        repeat_hint = ""
        if state.validator_failure_count >= REPAIR_FULL_PLAN_AFTER_SAME_FAILURES:
            repeat_hint = render_prompt_template(
                "validator_repair_repeat_hint.md",
                {"failure_count": state.validator_failure_count},
            )
        return render_prompt_template("validator_repair_hint.md", {"repeat_hint": repeat_hint})

    def _change_detector(self):
        ctx = self.ctx
        fingerprint = project_fingerprint(ctx.root, ctx.work)

        def changed() -> bool:
            nonlocal fingerprint
            latest = project_fingerprint(ctx.root, ctx.work)
            if latest == fingerprint:
                return False
            fingerprint = latest
            return True

        return changed


class ReviewStage(Stage):
    name = "review"

    def run(self, previous: Outcome | None = None) -> Outcome:
        ctx = self.ctx
        task = ctx.task
        if task is None or previous is None:
            raise RunnerError("review stage requires a task and execution result")
        ctx.set_stage("reviewing", "")
        if previous.status == "error":
            runner_status.set_status("Executor 異常但已有檔案變更，先執行 Review", task.title)
        review = review_task(ctx.args, ctx.root, ctx.work, ctx.state, task, task.last_output)
        task.last_review = review
        ctx.save_session()
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
        record_review_progress(task, ctx.root, ctx.work, outcome.feedback)
        ctx.save_state()
        runner_status.set_status("任務未完成，準備恢復", outcome.output)
        return outcome


class ValidateStage(Stage):
    name = "validate"

    def run(self, previous: Outcome | None = None) -> Outcome:
        ctx = self.ctx
        detail = (
            "AI · new session"
            if ctx.ai_validation
            else ctx.validator.name + (" + AI vote" if ctx.args.ai_validator_prompt.strip() else "")
        )
        ctx.set_stage("validating", "")
        runner_status.start("正在執行最終驗證", detail)
        try:
            try:
                passed, output = self._validate()
                outcome = Outcome("validate", "pass" if passed else "fail", output=output)
            except RunnerError as error:
                outcome = Outcome("validate", "error", output=str(error), error=error)
        finally:
            runner_status.stop()
        ctx.state.validator_output = bounded_text(outcome.output, MAX_VALIDATOR_OUTPUT_CHARS)
        return outcome

    def _validate(self) -> tuple[bool, str]:
        ctx = self.ctx
        if ctx.ai_validation:
            prompt = ctx.args.ai_validator_prompt.strip() or ctx.args.validator_prompt
            return run_ai_validator(
                ctx.args, ctx.root, ctx.work, ctx.state,
                MODEL_CALL_ERRORS_BEFORE_TASK_RETRY, prompt,
            )
        assert ctx.validator is not None
        passed, output = run_file_validator(
            ctx.validator, ctx.root, ctx.state_file,
            ctx.args.validator_timeout, ctx.args.validator_arg,
        )
        prompt = ctx.args.ai_validator_prompt
        if not passed or not prompt.strip():
            return passed, output
        ai_passed, ai_output = run_ai_validator(
            ctx.args, ctx.root, ctx.work, ctx.state,
            MODEL_CALL_ERRORS_BEFORE_TASK_RETRY, prompt,
        )
        return ai_passed, "FILE_VALIDATION_PASS\n" + ai_output


__all__ = ["ExecuteStage", "PlanningStage", "ReviewStage", "Stage", "StageContext", "ValidateStage"]
