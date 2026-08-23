"""Small graph-driven orchestration loop; stage details live outside the Runner."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from ..agent import create_agent
from ..agent.prompts import bounded_text
from ..app.script_runner import execute_script as execute_yaml_script
from ..config import RuntimeConfig
from ..config.defaults import MAX_TASK_OUTPUT_CHARS, REPAIR_FULL_PLAN_AFTER_SAME_FAILURES
from ..errors import RunnerError, backend_diagnostic_parts
from ..runtime import status as runner_status
from ..runtime.project_state import cleanup_stale_artifacts
from ..workflow.flow import default_flow
from ..workflow.stages import ExecuteStage, PlanningStage, ReviewStage, StageContext, ValidateStage
from .models import RunStage, Task
from .recovery import Outcome, Transition, decide, escalate_task_recovery, validator_failure_key
from .state_store import StateStore
from .transitions import complete_run, complete_task, install_plan, invalidate_plan, normalize_state, set_stage

show_todo = runner_status.show_todo


class TaskRunner:
    """Run one graph of independent stages until Final Validator completion."""

    def __init__(self, args: RuntimeConfig | argparse.Namespace) -> None:
        self.args = args if isinstance(args, RuntimeConfig) else RuntimeConfig.from_namespace(args)
        if not self.args.validator:
            raise RunnerError("--validator is required unless --script is used")
        self.root = Path(self.args.project_root).resolve()
        self.ai_validation = self.args.validator.lower() == "ai"
        self.validator = None if self.ai_validation else Path(self.args.validator).resolve()
        self.work = self.root / self.args.work_dir
        self.state_store = StateStore(self.root, self.work)
        self.state_file = self.state_store.path
        self._validate_paths()
        cleanup_stale_artifacts(self.work)

        self.state = self.state_store.load_or_create(
            self.args.goal, resume=self.args.resume, force_new=self.args.force_new
        )
        self.agent = create_agent(
            self.args,
            self.root,
            self.work / "debug",
            session_id=self.state.agent_session_id,
            timeout=self.args.agent_timeout,
        )
        self.backend_files = self.agent.prepare_project()
        self.agent.update_goal_reference(self.args.goal_file)
        if not self.args.resume:
            self._save_state()
        if normalize_state(self.state):
            self._save_state()
        runner_status.bind(self.state)

        self.context = StageContext(
            args=self.args,
            root=self.root,
            work=self.work,
            state=self.state,
            agent=self.agent,
            state_file=self.state_file,
            validator=self.validator,
            ai_validation=self.ai_validation,
            save_state=self._save_state,
            set_stage=self._set_stage,
        )
        stages = (
            PlanningStage(self.context),
            ExecuteStage(self.context),
            ReviewStage(self.context),
            ValidateStage(self.context),
        )
        self.flow = default_flow(*stages)

    def run(self) -> int:
        # Plan-only means exactly that, including resume of an already planned run.
        if self.args.plan_only and self.state.tasks:
            runner_status.set_status("Plan ready", "plan-only completed without execution")
            return 0
        stage_name = self.flow.entry(self.context)
        previous: Outcome | None = None
        while not self.state.completed and stage_name is not None:
            stage = self.flow.stage(stage_name)
            if stage_name == "execute":
                task = self.context.task
                if task is None:
                    raise RunnerError("flow entered execute without a pending task")
                task.attempts += 1
                self._save_state()
                runner_status.show_todo(self.state)

            outcome = stage.run(previous)
            transition = decide(
                outcome,
                task=self.context.task if stage_name in {"execute", "review"} else None,
                threshold=self.args.task_recovery_threshold,
            )
            self._apply(stage_name, outcome, transition)

            if self.args.plan_only and stage_name == "planning" and transition.action == "advance":
                runner_status.set_status("Plan ready", "plan-only completed without execution")
                return 0
            if self.state.completed:
                break

            next_stage = self.flow.next(stage_name, transition.action, self.context)
            previous = outcome if next_stage == "review" else None
            stage_name = next_stage
        return 0

    def _apply(self, stage: str, outcome: Outcome, transition: Transition) -> None:
        if stage == "planning":
            if transition.action != "advance" or not isinstance(outcome.data, list):
                raise RunnerError("planning stage did not produce a usable plan")
            install_plan(self.state, outcome.data, self.agent.session_id)
            self._save_state()
            runner_status.show_todo(self.state)
            return

        if stage == "execute":
            task = self._require_task()
            if outcome.error is not None:
                self._log_execution_outcome(task, outcome, transition)
            if transition.action == "retry":
                self._prepare_task_retry(task, transition.retry_session, transition.reason)
            elif transition.action == "replan":
                self._replan_stuck_task(task, transition.reason)
            return

        if stage == "review":
            task = self._require_task()
            if transition.action == "advance":
                complete_task(self.state, task, self.agent.session_id)
                self._save_state()
                runner_status.set_status("任務完成", task.title)
            elif transition.action == "retry":
                self._prepare_task_retry(task, transition.retry_session, transition.reason)
            else:
                self._replan_stuck_task(task, transition.reason)
            return

        if stage == "validate":
            self._apply_validation(outcome, transition)
            return

        raise RunnerError(f"unknown flow stage: {stage}")

    def _apply_validation(self, outcome: Outcome, transition: Transition) -> None:
        self._save_state()
        if transition.action == "retry":
            self._set_stage("validator_retry_wait", outcome.output)
            runner_status.set_status("Validator 無法執行，稍後重試", outcome.output[-1000:])
            if self.args.retry_delay:
                time.sleep(self.args.retry_delay)
            return
        if transition.action == "advance":
            self.agent.session_id = ""
            complete_run(self.state)
            self._set_stage("completed")
            runner_status.set_status("全部完成", "Validator PASS")
            return

        self._record_validator_failure(outcome.output)
        full_replan = (
            self.state.validator_failure_count >= REPAIR_FULL_PLAN_AFTER_SAME_FAILURES
            or bool(self.args.full_replan_threshold and self.state.cycle >= self.args.full_replan_threshold)
        )
        if full_replan:
            self.agent.session_id = ""
            self.state.agent_session_id = ""
        invalidate_plan(
            self.state,
            "Full planning requested after repeated recovery failures." if full_replan else "",
        )
        self._save_state()
        validator_name = (
            "AI FAIL" if self.ai_validation
            else "AI vote FAIL" if outcome.output.startswith("FILE_VALIDATION_PASS\n")
            else "file validator FAIL"
        )
        runner_status.set_status("最終驗證失敗，保留修改並重新拆分", validator_name)
        runner_status.show_todo(self.state)

    def _validate_paths(self) -> None:
        if not self.root.is_dir() or (self.validator is not None and not self.validator.is_file()):
            raise RunnerError("invalid project root or validator")

    def _save_state(self) -> None:
        self.state_store.save(self.state)

    def _set_stage(self, stage: RunStage, detail: str = "") -> None:
        set_stage(self.state, stage, detail)
        self._save_state()

    def _require_task(self) -> Task:
        task = self.context.task
        if task is None:
            raise RunnerError("task transition requires a pending task")
        return task

    def _prepare_task_retry(self, task: Task, retry_session: str = "same", reason: str = "") -> None:
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
            runner_status.set_status("恢復策略升級：改用 fresh session", task.title)
        self._set_stage("task_retry_wait", reason)
        runner_status.show_todo(self.state)
        if self.args.retry_delay:
            time.sleep(self.args.retry_delay)

    def _replan_stuck_task(self, task: Task, reason: str) -> None:
        feedback = bounded_text(
            f"Previous plan stalled on TODO {task.id} ({task.title}). "
            f"Recovery reason: {reason}. Latest evidence: {task.last_output}",
            MAX_TASK_OUTPUT_CHARS,
        )
        self.agent.session_id = ""
        invalidate_plan(self.state, feedback)
        self._save_state()
        runner_status.set_status("目前 TODO 持續無法推進，保留成果並重新規劃", task.title)

    def _record_validator_failure(self, output: str) -> None:
        key = validator_failure_key(output)
        if key == self.state.validator_failure_key:
            self.state.validator_failure_count += 1
        else:
            self.state.validator_failure_key = key
            self.state.validator_failure_count = 1
        self._set_stage("validator_failed", output)

    def _log_execution_outcome(self, task: Task, outcome: Outcome, transition: Transition) -> None:
        assert outcome.error is not None
        shown = outcome.changed_files[:20]
        changed = ",".join(shown) if shown else "-"
        if len(outcome.changed_files) > len(shown):
            changed += f",...(+{len(outcome.changed_files) - len(shown)})"
        details = [
            f"outcome={outcome.status}",
            f"session={self.agent.session_id or '-'}",
            f"changed_files={len(outcome.changed_files)}:{changed}",
            f"task_changed_files={len(task.changed_files)}",
            f"stagnant_attempts={task.stagnant_attempts}",
            f"failure_signature={task.progress_key[:12] or '-'}",
            f"task_recovery_action={transition.action}",
            f"retry_session={transition.retry_session}",
            *backend_diagnostic_parts(outcome.error, include_output=True),
            str(outcome.error)[-1000:],
        ]
        runner_status.set_status("模型階段失敗，套用統一恢復策略", " | ".join(details))


def execute(args: RuntimeConfig | argparse.Namespace) -> int:
    from ..app.execution import execute as app_execute
    return app_execute(args)


def execute_script(args: RuntimeConfig) -> int:
    from ..app.execution import execute as app_execute
    return execute_yaml_script(args, app_execute)
