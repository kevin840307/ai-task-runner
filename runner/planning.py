"""Planning flow: inspect, finalize, refine, and judge one task plan."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .agent import AgentClient
from .agent_args import planning_agent_args
from .debug import parse_with_debug
from .errors import RunnerError, diagnostic_error
from .models import RunState, Task
from .prompting import (
    plan_finalize_prompt,
    plan_judge_prompt,
    plan_refine_prompt,
    plan_understand_prompt,
)
from .model_results import parse_plan_judgment, parse_tasks
from .support import readonly_ask, retry_model_call
from .ui import LiveUI


MIN_PLANNED_TASKS = 6
PLAN_JUDGE_MAX_REWRITES = 2


def planning_agent_root(backend: str, root: Path, work: Path) -> Path:
    """Keep non-inspecting Qwen planning sessions isolated from source cwd."""
    return work if backend == "qwen" else root


def build_plan(
    args: argparse.Namespace,
    root: Path,
    work: Path,
    state: RunState,
    protected: Sequence[Path],
    ui: LiveUI,
    main_agent: AgentClient,
) -> list[Task]:
    """Build one current-cycle plan without changing planning semantics."""
    planner_root = planning_agent_root(args.backend, root, work)
    min_tasks = MIN_PLANNED_TASKS if state.cycle == 1 else 1
    project_changed: list[str] = []
    debug_dir = work / "debug"

    def new_planner(
        allow_project_read: bool = False,
        session_id: str = "",
    ) -> AgentClient:
        planner = AgentClient(
            backend=args.backend,
            command=args.command,
            root=root if allow_project_read or session_id else planner_root,
            extra_args=planning_agent_args(
                args.backend,
                args.agent_arg,
                allow_project_read=allow_project_read,
            ),
            session_id=session_id,
            timeout=args.planning_timeout,
            debug_dir=debug_dir,
        )
        planner.prepare_project()
        return planner

    def parse_plan(text: str) -> list[Task]:
        return parse_with_debug(
            debug_dir,
            parse_tasks,
            text,
            state.cycle,
            min_tasks=min_tasks,
            require_deliverable=True,
        )

    def salvage_plan(agent: AgentClient, error: RunnerError) -> list[Task] | None:
        diagnostic = diagnostic_error(error)
        raw = getattr(diagnostic, "output", "") if diagnostic else ""
        if not raw:
            return None
        try:
            return parse_plan(agent._decode(raw))
        except Exception:
            return None

    def ask_plan(
        planner: AgentClient,
        prompt: str,
        *,
        preserve_session: bool = False,
    ) -> list[Task]:
        try:
            output, protected_changed, changed = readonly_ask(
                planner,
                prompt,
                root,
                work,
                protected,
                timeout=args.planning_timeout,
                idle_timeout=args.agent_idle_after_change_timeout,
                preserve_session_on_error=preserve_session,
            )
            if protected_changed:
                raise RunnerError(
                    "AI modified files during planning and they were restored: "
                    + ", ".join(protected_changed)
                )
            project_changed.extend(changed)
            return parse_plan(output)
        except RunnerError as error:
            salvaged = salvage_plan(planner, error)
            if salvaged is not None:
                ui.set(
                    "AI 規劃程序異常但已取得有效規劃",
                    "using usable model output",
                )
                return salvaged
            raise

    draft_planner = new_planner(allow_project_read=True)
    inspection_summary = ""
    inspection_error: RunnerError | None = None
    ui.set(
        "AI 正在理解專案",
        "bounded read-only planning inspection",
    )
    try:
        inspection_summary, protected_changed, changed = readonly_ask(
            draft_planner,
            plan_understand_prompt(
                state.goal,
                root,
                state,
                protected,
                work,
            ),
            root,
            work,
            protected,
            timeout=args.planning_timeout,
            idle_timeout=args.agent_idle_after_change_timeout,
            preserve_session_on_error=True,
        )
        if protected_changed:
            raise RunnerError(
                "AI modified files during planning and they were restored: "
                + ", ".join(protected_changed)
            )
        project_changed.extend(changed)
    except RunnerError as error:
        inspection_error = error

    tasks: list[Task] | None = None
    if draft_planner.session_id:
        ui.set(
            "AI 正在產生任務規劃",
            "reuse completed planning inspection without tools",
        )
        planner = new_planner(session_id=draft_planner.session_id)
        try:
            tasks = ask_plan(
                planner,
                plan_finalize_prompt(
                    state.goal,
                    root,
                    state,
                    work,
                    same_session=True,
                ),
            )
        except RunnerError as error:
            inspection_error = error

    if tasks is None:
        ui.set(
            "AI 正在建立最小任務規劃",
            "fresh no-tool fallback",
        )

        def minimal_plan() -> list[Task]:
            planner = new_planner()
            return ask_plan(
                planner,
                plan_finalize_prompt(
                    state.goal,
                    root,
                    state,
                    work,
                    same_session=False,
                    inspection_summary=inspection_summary,
                ),
            )

        tasks = retry_model_call(
            minimal_plan,
            ui,
            "AI 正在建立最小任務規劃",
            str(inspection_error or "planning session unavailable")[-500:],
            args.retry_wait,
            args.retry_max_wait,
        )

    judge_issues: list[str] = []
    for rewrite_round in range(1, PLAN_JUDGE_MAX_REWRITES + 1):
        ui.set(
            "AI 正在重寫任務規劃",
            f"round {rewrite_round}/{PLAN_JUDGE_MAX_REWRITES}",
        )
        try:
            refiner = new_planner()
            tasks = ask_plan(
                refiner,
                plan_refine_prompt(
                    state.goal,
                    root,
                    state,
                    tasks,
                    work,
                    judge_issues,
                ),
            )
        except RunnerError as error:
            ui.set(
                "AI 重寫規劃異常，保留目前有效規劃",
                str(error)[-500:],
            )

        ui.set(
            "AI 正在審查任務規劃",
            f"round {rewrite_round}/{PLAN_JUDGE_MAX_REWRITES}",
        )
        try:
            judge = new_planner()
            judgment_text, protected_changed, judge_changed = readonly_ask(
                judge,
                plan_judge_prompt(
                    state.goal,
                    root,
                    state,
                    tasks,
                    work,
                ),
                root,
                work,
                protected,
                timeout=args.planning_timeout,
                idle_timeout=args.agent_idle_after_change_timeout,
            )
            if protected_changed:
                raise RunnerError(
                    "AI modified files during planning and they were restored: "
                    + ", ".join(protected_changed)
                )
            project_changed.extend(judge_changed)
            judgment = parse_with_debug(
                debug_dir,
                parse_plan_judgment,
                judgment_text,
                len(tasks),
            )
        except RunnerError as error:
            ui.set(
                "AI 規劃審查異常，使用目前有效規劃",
                str(error)[-500:],
            )
            break

        judge_issues = [] if judgment["accepted"] else judgment["issues"]
        if not judge_issues:
            break
        ui.set(
            "AI 任務規劃未通過，重新拆分",
            "; ".join(judge_issues),
        )
    else:
        ui.set(
            "AI 任務規劃仍有疑慮，交由後續驗證閉環",
            "; ".join(judge_issues),
        )

    if project_changed:
        ui.set(
            "AI restored project changes made during planning",
            ", ".join(sorted(set(project_changed))),
        )
    if planner_root == root:
        main_agent.session_id = draft_planner.session_id
    return tasks


__all__ = [
    "MIN_PLANNED_TASKS",
    "PLAN_JUDGE_MAX_REWRITES",
    "build_plan",
    "planning_agent_root",
]
