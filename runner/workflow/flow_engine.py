"""Minimal durable Workflow state machine."""

from __future__ import annotations

import json
from typing import Any

from ..config.defaults import MAX_VALIDATOR_OUTPUT_CHARS
from ..errors import ConfigurationError
from ..utils import bounded_text
from .results import finish_run, finish_task
from .registry import create_stage
from .stages import StageContext, StageExecutor, StageResult


class FlowEngine:
    """Run Stage -> Result -> Route until completion or stop.

    Workflow semantics are intentionally small:
    - PASS defaults to the next Stage.
    - FAIL defaults to stop unless routes.fail overrides it.
    - ERROR is not routable: StageExecutor applies retry policy, then stops here.
    - routes may override PASS/FAIL with next/done/stop/or another Stage.
    - contiguous scope: task nodes repeat once per durable Task.

    Technical retry/session recovery belongs only to StageExecutor.
    """

    def __init__(self, context: StageContext) -> None:
        self.context = context
        self.workflow = context.config.workflow
        self.positions = {
            str(item["name"]): index
            for index, item in enumerate(self.workflow)
        }

    def run(self, executor: StageExecutor) -> int:
        state = self.context.state
        previous = self._restore_previous()

        while state.workflow_position < len(self.workflow) and not state.completed:
            limit = self.context.config.max_cycles
            if limit != -1 and state.cycle > limit:
                self.context.set_stage("max_cycles_exhausted", f"cycle limit {limit} reached")
                self.context.save_state()
                return 2
            position = state.workflow_position
            if self.workflow[position].get("scope") == "task":
                previous, stopped = self._run_task_block(position, executor, previous)
            else:
                previous, stopped = self._run_stage(
                    position, executor, previous, task_scoped=False
                )
            if stopped:
                return 1

        if not state.completed and state.workflow_position >= len(self.workflow):
            finish_run(self.context)
            self.context.save_state()
        return 0

    def _run_task_block(
        self,
        position: int,
        executor: StageExecutor,
        previous: StageResult | None,
    ) -> tuple[StageResult | None, bool]:
        state = self.context.state
        start, end = self._task_block(position)
        if not state.tasks:
            raise ConfigurationError(
                "task-scoped workflow requires tasks from an earlier Stage"
            )
        if state.workflow_position != start:
            state.workflow_position = start

        while state.current < len(state.tasks):
            if not 0 <= state.task_step <= end - start:
                raise ConfigurationError("saved task_step is outside task-scoped flow")

            while state.task_step < end - start:
                index = start + state.task_step
                previous, stopped = self._run_stage(
                    index, executor, previous, task_scoped=True
                )
                if stopped:
                    return previous, True
                if state.workflow_position != start:
                    return previous, False

            finish_task(self.context)
            state.task_step = 0
            state.transition_previous = {}
            previous = None
            self.context.save_state()

        state.workflow_position = end
        state.task_step = 0
        self.context.save_state()
        return previous, False

    def _run_stage(
        self,
        index: int,
        executor: StageExecutor,
        previous: StageResult | None,
        *,
        task_scoped: bool,
    ) -> tuple[StageResult, bool]:
        definition = self.workflow[index]
        stage = create_stage(definition)
        label = str(definition.get("label", "") or "")
        policy = definition.get("error_policy")
        if policy:
            result = executor.run(
                stage, self.context, previous, label=label,
                retry_limit=policy["retries"],
            )
        else:
            result = executor.run(stage, self.context, previous, label=label)
        self._remember_previous(result)

        target = (
            resolve_handoff_target(definition, result)
            if definition.get("type") == "handoff" and result.status == "pass"
            else resolve_stage_target(definition, result.status)
        )
        if self._round_limit_reached(definition, index, target):
            limit = int(definition["max_rounds"])
            self.context.set_stage(
                "max_rounds_exhausted",
                f"{definition['name']} round limit {limit} reached",
            )
            self.context.save_state()
            return result, True
        if target == "stop":
            self.context.save_state()
            return result, True
        if target == "done":
            finish_run(self.context)
            self.context.save_state()
            return result, False
        if target == "next":
            if task_scoped:
                self.context.state.task_step += 1
            else:
                self.context.state.workflow_position = index + 1
                self.context.state.task_step = 0
            self.context.save_state()
            return result, False

        self._route_to(target, index, result)
        self.context.save_state()
        return result, False

    def _round_limit_reached(
        self,
        definition: dict[str, Any],
        source_index: int,
        target: str,
    ) -> bool:
        limit = definition.get("max_rounds")
        if limit is None or target not in self.positions:
            return False
        return self.positions[target] <= source_index and self.context.state.cycle >= int(limit)

    def _route_to(self, target: str, source_index: int, result: StageResult) -> None:
        position = self.positions[target]
        state = self.context.state

        if position <= source_index:
            state.cycle += 1

        if self.workflow[position].get("scope") == "task":
            start, _ = self._task_block(position)
            state.workflow_position = start
            state.task_step = position - start
        else:
            state.workflow_position = position
            state.task_step = 0

        self.context.set_stage("workflow_route", result.output)

    def _task_block(self, position: int) -> tuple[int, int]:
        start = position
        while start > 0 and self.workflow[start - 1].get("scope") == "task":
            start -= 1
        end = position
        while end < len(self.workflow) and self.workflow[end].get("scope") == "task":
            end += 1
        return start, end

    def _remember_previous(self, result: StageResult) -> None:
        raw = json.dumps(result.data, ensure_ascii=False, default=str)
        data = (
            json.loads(raw)
            if len(raw) <= MAX_VALIDATOR_OUTPUT_CHARS
            else {
                "_truncated": True,
                "text": bounded_text(raw, MAX_VALIDATOR_OUTPUT_CHARS),
            }
        )
        self.context.state.transition_previous = {
            "stage": result.stage,
            "status": result.status,
            "output": bounded_text(result.output, MAX_VALIDATOR_OUTPUT_CHARS),
            "changed_files": list(result.changed_files),
            "data": data,
            "kind": result.kind,
        }

    def _restore_previous(self) -> StageResult | None:
        saved = self.context.state.transition_previous
        if not saved:
            return None
        status = str(saved.get("status", ""))
        if status not in {"pass", "fail", "error"}:
            return None
        changed = saved.get("changed_files")
        return StageResult(
            stage=str(saved.get("stage", "stage")),
            status=status,
            output=str(saved.get("output", "")),
            changed_files=(
                [str(item) for item in changed if isinstance(item, str)]
                if isinstance(changed, list)
                else []
            ),
            data=saved.get("data"),
            kind=str(saved.get("kind", "generic")),
        )



def resolve_handoff_target(
    definition: dict[str, Any],
    result: StageResult,
) -> str:
    """Resolve one model-selected target from a Handoff Stage allow-list."""
    data = result.data
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"handoff stage {definition['name']} returned no structured target"
        )
    target = str(data.get("target", "") or "")
    allowed = definition.get("targets") or []
    if target not in allowed:
        raise ConfigurationError(
            f"handoff stage {definition['name']} selected disallowed target: {target}"
        )
    return target


def resolve_stage_target(definition: dict[str, Any], status: str) -> str:
    """Resolve semantic PASS/FAIL routing; technical ERROR always stops."""
    if status == "error":
        return "stop"
    routes = definition.get("routes")
    if isinstance(routes, dict) and status in routes:
        return str(routes[status])
    return "next" if status == "pass" else "stop"


def build_flow_engine(context: StageContext) -> FlowEngine:
    return FlowEngine(context)


__all__ = ["FlowEngine", "build_flow_engine", "resolve_handoff_target", "resolve_stage_target"]
