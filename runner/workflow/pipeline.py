"""Execute normalized declarative flow nodes."""

from __future__ import annotations

import json

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..errors import RunnerError
from .registry import create_stage
from .rules import finish_run, finish_task, prepare_replan
from .stages import Stage, StageContext, StageExecutor, StageResult
from .stages.plan_stage import build_task_steps


@dataclass(frozen=True)
class FlowNode:
    """One Stage plus the routing/runtime facts owned by the workflow engine."""

    stage: Stage
    recover: tuple[dict[str, Any], ...] = ()
    restart_at: str | None = None
    max_results: int | None = None
    workflow_index: int | None = None
    task_index: int | None = None
    task_last: bool = False

    @classmethod
    def from_definition(cls, definition: dict[str, Any]) -> "FlowNode":
        return cls(
            create_stage(definition),
            tuple(definition.get("recover", ())),
            definition.get("restart_at"),
            definition.get("max_results"),
            definition.get("_workflow_index"),
            definition.get("_task_index"),
            bool(definition.get("_task_last", False)),
        )


class Pipeline:
    """Small interpreter for static flow, generated steps, recovery, and restart."""

    def __init__(self, context: StageContext, flow: Iterable[dict[str, Any]]) -> None:
        self.context = context
        self.workflow = list(flow)
        self.positions = {
            item["name"]: index
            for index, item in enumerate(self.workflow)
            if item.get("name")
        }

    def run(self, executor: StageExecutor, *, plan_only: bool = False) -> int:
        previous: StageResult | None = None
        stop = False
        replacement: tuple[dict[str, Any], ...] | None = None

        if not self._has_dynamic_steps():
            self._restore_dynamic_steps()
        if self._has_dynamic_steps():
            replacement, previous, stop = self._run_dynamic(
                executor, plan_only, previous
            )

        flow = list(replacement) if replacement is not None else self._initial_flow()
        while flow and not stop and not self.context.state.completed:
            replacement, previous, stop = self._run_steps(
                flow, executor, plan_only, previous
            )
            flow = list(replacement or ())

        if (
            not plan_only
            and not stop
            and previous is not None
            and previous.status == "pass"
            and self.context.state.workflow_position >= len(self.workflow)
        ):
            finish_run(self.context)
            self.context.save_state()
        return 0

    def _run_steps(
        self,
        flow: Iterable[dict[str, Any]],
        executor: StageExecutor,
        plan_only: bool,
        previous: StageResult | None,
    ) -> tuple[tuple[dict[str, Any], ...] | None, StageResult | None, bool]:
        for definition in flow:
            node = FlowNode.from_definition(definition)
            while True:
                pending = self._limited_result_pending_recover(node)
                if pending is not None:
                    replacement, recovered, stop = self._run_steps(
                        node.recover, executor, plan_only, pending
                    )
                    if replacement is not None or stop:
                        return replacement, recovered or pending, stop
                    previous = recovered or pending
                    result = previous
                    self._clear_limited_result(node)
                    break

                result = executor.run(node.stage, self.context, previous)
                limit_reached = self._record_limited_result(node, result)

                if result.status == "replan":
                    prepare_replan(self.context, result)
                if result.status == "replan" or (
                    result.status == "fail" and node.restart_at is not None
                ):
                    return self._restart(node.restart_at, result), result, False

                if result.status == "fail" and node.recover:
                    replacement, recovered, stop = self._run_steps(
                        node.recover, executor, plan_only, result
                    )
                    if replacement is not None or stop:
                        return replacement, recovered or result, stop
                    previous = recovered or result
                    if limit_reached:
                        result = previous
                        self._clear_limited_result(node)
                        break
                    continue
                if result.status == "pass":
                    self._clear_limited_result(node)
                break

            if result.status in {"fail", "error"}:
                return None, result, True

            if result.next_steps:
                if node.task_index is not None:
                    raise RunnerError("generated task Stage cannot emit next_steps")
                self._start_dynamic_steps(result.next_steps)

            if plan_only and getattr(node.stage, "plan_only_stop", False):
                self.context.save_state()
                return None, result, True

            effective_result = result
            if result.next_steps:
                replacement, generated, stop = self._run_dynamic(
                    executor, plan_only, result
                )
                effective_result = generated or result
                if replacement is not None or stop:
                    return replacement, effective_result, stop

            if node.task_last:
                finish_task(self.context)

            self._advance(node)
            self.context.save_state()
            previous = effective_result
        return None, previous, False

    def _run_dynamic(
        self,
        executor: StageExecutor,
        plan_only: bool,
        previous: StageResult | None,
    ) -> tuple[tuple[dict[str, Any], ...] | None, StageResult | None, bool]:
        state = self.context.state
        while state.dynamic_index < len(state.dynamic_steps):
            definition = state.dynamic_steps[state.dynamic_index]
            task_index = definition.get("_task_index")
            if isinstance(task_index, int):
                if state.current > task_index:
                    state.dynamic_index += 1
                    self.context.save_state()
                    continue
                if state.current < task_index:
                    raise RunnerError(
                        "generated workflow reached the next TODO before completing the current TODO"
                    )

            replacement, previous, stop = self._run_steps(
                [definition],
                executor,
                plan_only,
                previous,
            )
            if replacement is not None or stop:
                return replacement, previous, stop
            state.dynamic_index += 1
            self.context.save_state()

        current = self._current_definition()
        self._clear_dynamic_steps()
        if current and current.get("planner_stages"):
            state.workflow_position += 1
        self.context.save_state()
        return None, previous, False

    def _start_dynamic_steps(
        self,
        steps: list[dict[str, Any]],
    ) -> None:
        if not steps:
            return
        state = self.context.state
        state.dynamic_steps = [dict(step) for step in steps]
        state.dynamic_index = 0
        self.context.save_state()

    def _restore_dynamic_steps(self) -> None:
        """Recover generated work if a crash happened before Pipeline queued it."""
        state = self.context.state
        if state.current >= len(state.tasks):
            return
        current = self._current_definition()
        if current is None:
            return

        plan = current if current.get("planner_stages") else self._find_plan(
            current.get("recover", ())
        )
        if not plan:
            return
        steps = build_task_steps(
            state.tasks,
            plan.get("planner_stages", {}),
            start=state.current,
        )
        self._start_dynamic_steps(steps)

    def _current_definition(self) -> dict[str, Any] | None:
        position = self.context.state.workflow_position
        return self.workflow[position] if position < len(self.workflow) else None

    @classmethod
    def _find_plan(cls, flow: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
        for definition in flow:
            if definition.get("planner_stages"):
                return definition
            nested = cls._find_plan(definition.get("recover", ()))
            if nested is not None:
                return nested
        return None

    def _has_dynamic_steps(self) -> bool:
        state = self.context.state
        return state.dynamic_index < len(state.dynamic_steps)

    def _clear_dynamic_steps(self) -> None:
        state = self.context.state
        state.dynamic_steps = []
        state.dynamic_index = 0

    def _initial_flow(self) -> list[dict[str, Any]]:
        if self.context.state.completed:
            return []
        remaining = self.workflow[self.context.state.workflow_position :]
        if self.context.state.stage == "validator_failed" and remaining:
            recover = remaining[0].get("recover", ())
            if recover:
                return [*recover, *remaining]
        return list(remaining)

    def _advance(self, node: FlowNode) -> None:
        if node.workflow_index is not None:
            self.context.state.workflow_position = max(
                self.context.state.workflow_position, node.workflow_index + 1
            )

    def _record_limited_result(self, node: FlowNode, result: StageResult) -> bool:
        if node.max_results is None or result.status not in {"pass", "fail"}:
            return False
        state = self.context.state
        key = self._result_limit_key(node)
        if state.flow_result_key != key:
            state.flow_result_key = key
            state.flow_result_count = 0
        state.flow_result_count += 1
        if result.status == "fail":
            state.flow_result_previous = {
                "stage": result.stage,
                "status": result.status,
                "output": result.output,
                "data": json.loads(json.dumps(result.data, ensure_ascii=False, default=str)),
            }
        self.context.save_state()
        return result.status == "fail" and state.flow_result_count >= node.max_results

    def _limited_result_pending_recover(self, node: FlowNode) -> StageResult | None:
        if node.max_results is None:
            return None
        state = self.context.state
        if (
            state.flow_result_key != self._result_limit_key(node)
            or state.flow_result_count < node.max_results
            or not state.flow_result_previous
        ):
            return None
        saved = state.flow_result_previous
        return StageResult(
            str(saved.get("stage", node.stage.name)),
            "fail",
            output=str(saved.get("output", "")),
            data=saved.get("data"),
        )

    def _clear_limited_result(self, node: FlowNode) -> None:
        if node.max_results is None:
            return
        state = self.context.state
        if state.flow_result_key == self._result_limit_key(node):
            state.flow_result_key = ""
            state.flow_result_count = 0
            state.flow_result_previous = {}

    @staticmethod
    def _result_limit_key(node: FlowNode) -> str:
        if node.workflow_index is not None:
            return f"workflow:{node.workflow_index}"
        if node.task_index is not None:
            return f"task:{node.task_index}:{node.stage.name}"
        spec = getattr(node.stage, "spec", None)
        prompt = getattr(spec, "prompt", "")
        return f"stage:{node.stage.name}:{prompt}"

    def _restart(
        self, target: str | None, result: StageResult
    ) -> tuple[dict[str, Any], ...]:
        target = target or next(iter(self.positions), "")
        if target not in self.positions:
            raise ValueError(f"restart target is not a top-level Stage: {target}")
        position = self.positions[target]
        self.context.state.workflow_position = position
        self.context.set_stage("workflow_restart", result.output)
        self.context.save_state()
        return tuple(self.workflow[position:])


def build_pipeline(context: StageContext) -> Pipeline:
    return Pipeline(context, context.config.workflow)


__all__ = ["FlowNode", "Pipeline", "build_pipeline"]
