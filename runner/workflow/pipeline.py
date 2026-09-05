"""Execute a static declarative SOP over durable planned TODOs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..errors import RunnerError
from .recovery import RecoveryPolicy
from .registry import create_stage
from .rules import finish_run, finish_task, prepare_replan
from .stages import Stage, StageContext, StageExecutor, StageResult


@dataclass(frozen=True)
class FlowNode:
    """One Stage plus routing/runtime facts owned by the workflow engine."""

    stage: Stage
    recover: tuple[dict[str, Any], ...] = ()
    restart_at: str | None = None
    repeat: int | None = None
    fresh_after_same_failures: int | None = None
    label: str = ""
    scope: str = ""
    workflow_index: int | None = None

    @classmethod
    def from_definition(cls, definition: dict[str, Any]) -> "FlowNode":
        return cls(
            create_stage(definition),
            tuple(definition.get("recover", ())),
            definition.get("restart_at"),
            definition.get("repeat"),
            definition.get("fresh_after_same_failures"),
            str(definition.get("label", "") or ""),
            str(definition.get("scope", "") or ""),
            definition.get("_workflow_index"),
        )


class Pipeline:
    """Run static top-level stages and repeat task-scoped stages for every TODO."""

    def __init__(self, context: StageContext, flow: Iterable[dict[str, Any]]) -> None:
        self.context = context
        self.workflow = [
            {**item, "_workflow_index": item.get("_workflow_index", index)}
            for index, item in enumerate(flow)
        ]
        self.positions = {
            item["name"]: index
            for index, item in enumerate(self.workflow)
            if item.get("name")
        }
        self.recovery = RecoveryPolicy(context)
        self._task_generation = 0

    def run(self, executor: StageExecutor, *, plan_only: bool = False) -> int:
        state = self.context.state
        previous: StageResult | None = None
        stop = False

        # A previous final-validator failure resumes by running that validator's
        # configured repair plan before returning to the static task SOP.
        if state.stage == "validator_failed" and state.workflow_position < len(self.workflow):
            definition = self.workflow[state.workflow_position]
            recover = tuple(definition.get("recover", ()))
            if recover:
                generation = self._task_generation
                _, previous, stop = self._run_steps(recover, executor, plan_only, previous)
                if stop:
                    return 0
                if self._task_generation != generation and self._has_pending_task():
                    self._restart_task_sop()

        while (
            state.workflow_position < len(self.workflow)
            and not stop
            and not state.completed
        ):
            position = state.workflow_position
            definition = self.workflow[position]

            if definition.get("scope") == "task":
                end = self._task_block_end(position)
                replacement, previous, stop = self._run_task_block(
                    position, end, executor, plan_only, previous
                )
                if replacement is not None:
                    continue
                if stop:
                    break
                state.workflow_position = end
                state.task_step = 0
                self.context.save_state()
                continue

            replacement, previous, stop = self._run_steps(
                [definition], executor, plan_only, previous
            )
            if replacement is not None:
                continue
            if stop:
                break

        if (
            not plan_only
            and not stop
            and previous is not None
            and previous.status == "pass"
            and state.workflow_position >= len(self.workflow)
        ):
            finish_run(self.context)
            self.context.save_state()
        return 0

    def _run_task_block(
        self,
        start: int,
        end: int,
        executor: StageExecutor,
        plan_only: bool,
        previous: StageResult | None,
    ) -> tuple[tuple[dict[str, Any], ...] | None, StageResult | None, bool]:
        state = self.context.state
        block = self.workflow[start:end]
        if not block:
            raise RunnerError("task-scoped workflow block is empty")
        if not state.tasks:
            raise RunnerError(
                "task-scoped workflow requires tasks from an earlier Stage or input"
            )

        while state.current < len(state.tasks):
            if state.task_step > len(block):
                raise RunnerError("saved task_step is outside the task-scoped SOP")
            while state.task_step < len(block):
                definition = block[state.task_step]
                replacement, previous, stop = self._run_steps(
                    [definition], executor, plan_only, previous, advance_top_level=False
                )
                if replacement is not None or stop:
                    return replacement, previous, stop
                state.task_step += 1
                self.context.save_state()

            finish_task(self.context)
            state.task_step = 0
            self.context.save_state()
        return None, previous, False

    def _run_steps(
        self,
        flow: Iterable[dict[str, Any]],
        executor: StageExecutor,
        plan_only: bool,
        previous: StageResult | None,
        *,
        advance_top_level: bool = True,
    ) -> tuple[tuple[dict[str, Any], ...] | None, StageResult | None, bool]:
        for definition in flow:
            node = FlowNode.from_definition(definition)
            while True:
                pending = self.recovery.pending_recovery(node)
                if pending is not None:
                    replacement, recovered, stop = self._run_steps(
                        node.recover, executor, plan_only, pending, advance_top_level=False
                    )
                    if replacement is not None or stop:
                        return replacement, recovered or pending, stop
                    result = recovered or pending
                    self.recovery.clear_repeat(node)
                    break

                result = (
                    executor.run(node.stage, self.context, previous, label=node.label)
                    if node.label
                    else executor.run(node.stage, self.context, previous)
                )
                if result.status == "pass" and result.kind == "tasks":
                    self._task_generation += 1
                action = self.recovery.decide(node, result, executor)

                if action.kind == "replan":
                    prepare_replan(self.context, result)
                    return self._restart(node.restart_at, result), result, False
                if action.kind == "restart":
                    return self._restart(node.restart_at, result), result, False
                if action.kind == "stop":
                    return None, result, True
                if action.kind == "recover":
                    generation = self._task_generation
                    replacement, recovered, stop = self._run_steps(
                        node.recover, executor, plan_only, result, advance_top_level=False
                    )
                    if replacement is not None or stop:
                        return replacement, recovered or result, stop
                    previous = recovered or result
                    if self._task_generation != generation and self._has_pending_task():
                        return self._restart_task_sop(result), previous, False
                    if action.limit_reached:
                        result = previous
                        self.recovery.clear_repeat(node)
                        break
                    continue
                break

            if advance_top_level:
                self._advance(node)
            self.context.save_state()

            # Plan-only must persist the cursor *after* Planning. Otherwise a
            # later --resume reruns PlanStage even though durable TODOs already
            # exist instead of entering the task-scoped SOP.
            if plan_only and result.kind == "tasks":
                return None, result, True

            previous = result
        return None, previous, False

    def _advance(self, node: FlowNode) -> None:
        if node.workflow_index is not None:
            self.context.state.workflow_position = max(
                self.context.state.workflow_position, node.workflow_index + 1
            )

    def _task_block_end(self, start: int) -> int:
        end = start
        while end < len(self.workflow) and self.workflow[end].get("scope") == "task":
            end += 1
        return end

    def _task_block_start(self, position: int) -> int:
        start = position
        while start > 0 and self.workflow[start - 1].get("scope") == "task":
            start -= 1
        return start

    def _first_task_scope(self) -> int | None:
        for index, definition in enumerate(self.workflow):
            if definition.get("scope") == "task":
                return self._task_block_start(index)
        return None

    def _restart_task_sop(self, result: StageResult | None = None) -> tuple[dict[str, Any], ...]:
        start = self._first_task_scope()
        if start is None:
            raise RunnerError("task-producing recovery requires at least one task-scoped Stage")
        state = self.context.state
        state.workflow_position = start
        state.task_step = 0
        if result is not None:
            self.context.set_stage("workflow_restart", result.output)
        self.context.save_state()
        return tuple(self.workflow[start:])

    def _has_pending_task(self) -> bool:
        return self.context.state.current < len(self.context.state.tasks)

    def _restart(
        self, target: str | None, result: StageResult
    ) -> tuple[dict[str, Any], ...]:
        target = target or next(iter(self.positions), "")
        if target not in self.positions:
            raise ValueError(f"restart target is not a top-level Stage: {target}")
        position = self.positions[target]
        state = self.context.state
        if self.workflow[position].get("scope") == "task":
            start = self._task_block_start(position)
            state.workflow_position = start
            state.task_step = position - start
            position = start
        else:
            state.workflow_position = position
            state.task_step = 0
        self.context.set_stage("workflow_restart", result.output)
        self.context.save_state()
        return tuple(self.workflow[position:])


def build_pipeline(context: StageContext) -> Pipeline:
    return Pipeline(context, context.config.workflow)


__all__ = ["FlowNode", "Pipeline", "build_pipeline"]
