"""Planning flow: inspect, finalize, refine, and judge one task plan."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..agent import AgentClient
from ..agent.calls import recover_structured_output, retry_model_call
from ..agent.debug import parse_with_debug
from ..agent.prompts import (
    plan_finalize_prompt,
    plan_judge_prompt,
    plan_refine_prompt,
    plan_understand_prompt,
    structured_output_retry_prompt,
)
from ..agent.results import parse_plan_judgment, parse_tasks
from ..config import RuntimeConfig
from ..defaults import MIN_PLANNED_TASKS
from ..errors import RunnerError, diagnostic_error
from ..models import PlanJudgment, RunState, Task
from ..safety.project_guard import readonly_ask
from ..ui import LiveUI

PLAN_JUDGE_MAX_REWRITES = 2



@dataclass
class _PlanningFlow:
    args: RuntimeConfig
    root: Path
    work: Path
    state: RunState
    protected: Sequence[Path]
    ui: LiveUI
    planner: AgentClient
    project_changed: list[str] = field(default_factory=list)

    @property
    def debug_dir(self) -> Path:
        return self.work / "debug"

    def parse_plan(self, text: str) -> list[Task]:
        return parse_with_debug(
            self.debug_dir,
            parse_tasks,
            text,
            self.state.cycle,
            min_tasks=MIN_PLANNED_TASKS,
            require_deliverable=True,
        )

    def salvage_plan(self, error: RunnerError) -> list[Task] | None:
        diagnostic = diagnostic_error(error)
        raw = getattr(diagnostic, "output", "") if diagnostic else ""
        if not raw:
            return None
        try:
            return self.parse_plan(self.planner._decode(raw))
        except Exception:
            return None

    def ask_raw(self, prompt: str) -> str:
        output, protected_changed, changed = readonly_ask(
            self.planner,
            prompt,
            self.root,
            self.work,
            self.protected,
            timeout=self.args.planning_timeout,
            idle_timeout=self.args.agent_idle_after_change_timeout,
        )
        if protected_changed:
            raise RunnerError(
                "AI modified files during planning and they were restored: "
                + ", ".join(protected_changed)
            )
        self.project_changed.extend(changed)
        return output

    def ask_plan(self, prompt: str) -> list[Task]:
        try:
            output = self.ask_raw(prompt)
            return recover_structured_output(
                output,
                self.parse_plan,
                lambda error: self.ask_raw(structured_output_retry_prompt(error)),
            )
        except RunnerError as error:
            salvaged = self.salvage_plan(error)
            if salvaged is None:
                raise
            self.ui.set(
                "AI 規劃程序異常但已取得有效規劃",
                "using usable model output",
            )
            return salvaged

    def inspect_project(self) -> tuple[str, RunnerError | None]:
        prompt = plan_understand_prompt(
            self.state.goal,
            self.root,
            self.state,
            self.work,
        )
        self.ui.set("AI 正在理解專案", "bounded read-only planning inspection")
        try:
            summary = self.ask_raw(prompt)
            return summary, None
        except RunnerError as error:
            return "", error

    def create_initial_plan(
        self,
        inspection_summary: str,
        inspection_error: RunnerError | None,
    ) -> list[Task]:
        tasks: list[Task] | None = None
        if self.planner.session_id:
            prompt = plan_finalize_prompt(
                self.state.goal,
                self.root,
                self.state,
                self.work,
                same_session=True,
            )
            self.ui.set(
                "AI 正在產生任務規劃",
                "reuse completed planning inspection without tools",
            )
            try:
                tasks = self.ask_plan(prompt)
            except RunnerError as error:
                inspection_error = error
                if self.planner.session_id:
                    try:
                        tasks = self.ask_plan(prompt)
                    except RunnerError as retry_error:
                        inspection_error = retry_error

        if tasks is not None:
            return tasks

        self.planner.session_id = ""

        def minimal_plan() -> list[Task]:
            prompt = plan_finalize_prompt(
                self.state.goal,
                self.root,
                self.state,
                self.work,
                same_session=False,
                inspection_summary=inspection_summary,
            )
            self.ui.set(
                "AI 正在建立最小任務規劃",
                "fresh full-context fallback",
            )
            return self.ask_plan(prompt)

        return retry_model_call(
            minimal_plan,
            self.ui,
            "AI 正在準備最小任務規劃",
            str(inspection_error or "planning session unavailable")[-500:],
            self.args.retry_wait,
            self.args.retry_max_wait,
        )

    def judge_and_refine(self, tasks: list[Task]) -> list[Task]:
        for judge_round in range(PLAN_JUDGE_MAX_REWRITES + 1):
            try:
                judgment = self._judge(tasks, judge_round)
            except RunnerError as error:
                self.ui.set(
                    "AI 規劃審查異常，使用目前有效規劃",
                    str(error)[-500:],
                )
                break

            judge_issues = [] if judgment["accepted"] else judgment["issues"]
            if not judge_issues:
                break
            if judge_round == PLAN_JUDGE_MAX_REWRITES:
                self.ui.set(
                    "AI 任務規劃仍有疑慮，交由後續驗證閉環",
                    "; ".join(judge_issues),
                )
                break
            refined = self._refine(tasks, judge_issues, judge_round)
            if refined is None:
                break
            tasks = refined
        return tasks

    def _judge(self, tasks: list[Task], judge_round: int) -> PlanJudgment:
        prompt = plan_judge_prompt(
            self.state.goal,
            self.root,
            self.state,
            tasks,
            self.work,
            same_session=bool(self.planner.session_id),
        )
        self.ui.set(
            "AI 正在審查任務規劃",
            f"round {judge_round + 1}/{PLAN_JUDGE_MAX_REWRITES + 1}",
        )
        judgment_text = self.ask_raw(prompt)
        return recover_structured_output(
            judgment_text,
            lambda raw: parse_with_debug(
                self.debug_dir, parse_plan_judgment, raw
            ),
            lambda error: self.ask_raw(structured_output_retry_prompt(error)),
        )

    def _refine(
        self,
        tasks: list[Task],
        judge_issues: list[str],
        judge_round: int,
    ) -> list[Task] | None:
        prompt = plan_refine_prompt(
            self.state.goal,
            self.root,
            self.state,
            tasks,
            self.work,
            judge_issues,
            same_session=bool(self.planner.session_id),
        )
        self.ui.set(
            "AI 任務規劃未通過，正在重寫",
            f"round {judge_round + 1}/{PLAN_JUDGE_MAX_REWRITES} · "
            + "; ".join(judge_issues),
        )
        try:
            return self.ask_plan(prompt)
        except RunnerError as error:
            if not self.planner.session_id:
                self.ui.set(
                    "AI 重寫 session 無法使用，改用 fresh 規劃重寫",
                    str(error)[-500:],
                )
                try:
                    return self.ask_plan(
                        plan_refine_prompt(
                            self.state.goal,
                            self.root,
                            self.state,
                            tasks,
                            self.work,
                            judge_issues,
                            same_session=False,
                        )
                    )
                except RunnerError as retry_error:
                    error = retry_error
            self.ui.set(
                "AI 重寫規劃異常，保留目前有效規劃",
                str(error)[-500:],
            )
            return None

    def run(self) -> list[Task]:
        inspection_summary, inspection_error = self.inspect_project()
        tasks = self.create_initial_plan(inspection_summary, inspection_error)
        tasks = self.judge_and_refine(tasks)
        if self.project_changed:
            self.ui.set(
                "AI restored project changes made during planning",
                ", ".join(sorted(set(self.project_changed))),
            )
        return tasks


def build_plan(
    args: RuntimeConfig,
    root: Path,
    work: Path,
    state: RunState,
    protected: Sequence[Path],
    ui: LiveUI,
    main_agent: AgentClient,
) -> list[Task]:
    """Build one current-cycle plan without changing planning semantics."""
    return _PlanningFlow(
        args, root, work, state, protected, ui, main_agent
    ).run()


__all__ = [
    "MIN_PLANNED_TASKS",
    "PLAN_JUDGE_MAX_REWRITES",
    "build_plan",
]
