"""Linear FlowEngine over reusable Stage execution primitives."""

from __future__ import annotations

from collections.abc import Iterable
import json
from dataclasses import dataclass
from typing import Any

from ..config.defaults import MAX_VALIDATOR_OUTPUT_CHARS
from ..errors import RunnerError
from ..utils.text import bounded_text
from .semantic_routing import SemanticRoutingPolicy
from .registry import create_stage
from .routing import LinearRouting
from .reducers import finish_run, finish_task, prepare_replan
from .stages import Stage, StageContext, StageExecutor, StageResult


@dataclass(frozen=True)
class FlowNode:
    """One Stage plus routing/runtime facts owned by the workflow engine."""

    stage: Stage
    recover: tuple[dict[str, Any], ...] = ()
    restart_at: str | None = None
    repeat: int | None = None
    max_attempts: int | None = None
    on_exhausted: str | None = None
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
            definition.get("max_attempts"),
            definition.get("on_exhausted"),
            definition.get("fresh_after_same_failures"),
            str(definition.get("label", "") or ""),
            str(definition.get("scope", "") or ""),
            definition.get("_workflow_index"),
        )


class FlowEngine:
    """Run the current Linear Workflow while delegating cursor ownership."""

    def __init__(self, context: StageContext, flow: Iterable[dict[str, Any]]) -> None:
        self.context = context
        self.workflow = [
            {**item, "_workflow_index": item.get("_workflow_index", index)}
            for index, item in enumerate(flow)
        ]
        self.routing = LinearRouting(context, self.workflow)
        self.recovery = SemanticRoutingPolicy(context)
        self._task_generation = 0

    def run(self, executor: StageExecutor, *, plan_only: bool = False) -> int:
        state = self.context.state
        previous = self._restore_transition()
        stop = False

        while (
            state.workflow_position < len(self.workflow)
            and not stop
            and not state.completed
        ):
            position = state.workflow_position
            definition = self.workflow[position]

            if definition.get("scope") == "task":
                end = self.routing.task_block_end(position)
                replacement, previous, stop = self._run_task_block(
                    position, end, executor, plan_only, previous
                )
                if replacement is not None:
                    continue
                if stop:
                    break
                self.routing.complete_task_block(end)
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
        return 1 if stop and not state.completed else 0

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
                self.routing.advance_task_step()
                self.context.save_state()

            finish_task(self.context)
            self.routing.reset_task_step()
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
                bounded_pending = self.recovery.pending_bounded_recovery(node)
                if bounded_pending is not None:
                    generation = self._task_generation
                    replacement, recovered, stop = self._run_steps(
                        node.recover,
                        executor,
                        plan_only,
                        bounded_pending,
                        advance_top_level=False,
                    )
                    if replacement is not None or stop:
                        return replacement, recovered or bounded_pending, stop
                    self.recovery.complete_bounded_recovery(node)
                    previous = recovered or bounded_pending
                    if self._task_generation != generation and self._has_pending_task():
                        return self.routing.restart_task_sop(bounded_pending), previous, False
                    continue

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
                self._remember_transition(result)
                if result.status == "pass" and result.kind == "tasks":
                    self._task_generation += 1
                action = self.recovery.decide(node, result, executor)

                if action.kind == "replan":
                    prepare_replan(self.context, result)
                    return self.routing.restart(node.restart_at, result), result, False
                if action.kind == "restart":
                    if (
                        result.kind == "validation"
                        and self.routing.restart_target_produces_tasks(node.restart_at)
                    ):
                        prepare_replan(self.context, result)
                    return self.routing.restart(node.restart_at, result), result, False
                if action.kind == "stop":
                    return None, result, True
                if action.kind == "recover":
                    generation = self._task_generation
                    replacement, recovered, stop = self._run_steps(
                        node.recover, executor, plan_only, result, advance_top_level=False
                    )
                    if replacement is not None or stop:
                        return replacement, recovered or result, stop
                    self.recovery.complete_bounded_recovery(node)
                    previous = recovered or result
                    if self._task_generation != generation and self._has_pending_task():
                        return self.routing.restart_task_sop(result), previous, False
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

    def _restore_transition(self) -> StageResult | None:
        saved = self.context.state.transition_previous
        if not saved:
            return None
        status = str(saved.get("status", "pass"))
        if status not in {"pass", "fail", "error", "replan"}:
            return None
        kind = str(saved.get("kind", "generic"))
        if kind not in {"generic", "tasks", "task", "review", "validation"}:
            kind = "generic"
        changed_files = saved.get("changed_files", [])
        if not isinstance(changed_files, list):
            changed_files = []
        return StageResult(
            stage=str(saved.get("stage", "stage")),
            status=status,
            output=str(saved.get("output", "")),
            changed_files=[
                str(item) for item in changed_files if isinstance(item, str)
            ],
            skipped=bool(saved.get("skipped", False)),
            data=saved.get("data"),
            kind=kind,
        )

    def _remember_transition(self, result: StageResult) -> None:
        data_json = json.dumps(result.data, ensure_ascii=False, default=str)
        data = (
            json.loads(data_json)
            if len(data_json) <= MAX_VALIDATOR_OUTPUT_CHARS
            else {
                "_truncated": True,
                "text": bounded_text(data_json, MAX_VALIDATOR_OUTPUT_CHARS),
            }
        )
        # Do not save here. The transition context must commit together with
        # the next routing/cursor checkpoint; otherwise a crash could persist
        # a new previous result while leaving the cursor on the same Stage.
        self.context.state.transition_previous = {
            "stage": result.stage,
            "status": result.status,
            "output": bounded_text(result.output, MAX_VALIDATOR_OUTPUT_CHARS),
            "changed_files": list(result.changed_files),
            "skipped": result.skipped,
            "data": data,
            "kind": result.kind,
        }

    def _advance(self, node: FlowNode) -> None:
        self.routing.advance(node.workflow_index)

    def _has_pending_task(self) -> bool:
        return self.context.state.current < len(self.context.state.tasks)

def build_flow_engine(context: StageContext) -> FlowEngine:
    return FlowEngine(context, context.config.workflow)


__all__ = ["FlowEngine", "FlowNode", "build_flow_engine"]
