"""Linear routing state owner.

This module owns durable Linear workflow cursor mutations. Stage execution and
semantic result reduction must not change workflow_position/task_step directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..errors import RunnerError
from .registry import stage_result_kind
from .stages.contracts import StageContext, StageResult


class LinearRouting:
    """Own Linear workflow cursor/navigation state.

    Keep all workflow_position/task_step writes here so resume behavior and
    rollback semantics have one obvious owner.
    """

    def __init__(
        self,
        context: StageContext,
        workflow: Sequence[dict[str, Any]],
    ) -> None:
        self.context = context
        self.workflow = workflow
        self.positions = {
            item["name"]: index
            for index, item in enumerate(workflow)
            if item.get("name")
        }

    def advance(self, workflow_index: int | None) -> None:
        if workflow_index is None:
            return
        state = self.context.state
        state.workflow_position = max(state.workflow_position, workflow_index + 1)

    def advance_task_step(self) -> None:
        self.context.state.task_step += 1

    def reset_task_step(self) -> None:
        self.context.state.task_step = 0

    def complete_task_block(self, end: int) -> None:
        state = self.context.state
        state.workflow_position = end
        state.task_step = 0

    def task_block_end(self, start: int) -> int:
        end = start
        while end < len(self.workflow) and self.workflow[end].get("scope") == "task":
            end += 1
        return end

    def task_block_start(self, position: int) -> int:
        start = position
        while start > 0 and self.workflow[start - 1].get("scope") == "task":
            start -= 1
        return start

    def first_task_scope(self) -> int | None:
        for index, definition in enumerate(self.workflow):
            if definition.get("scope") == "task":
                return self.task_block_start(index)
        return None

    def restart_task_sop(
        self,
        result: StageResult | None = None,
    ) -> tuple[dict[str, Any], ...]:
        start = self.first_task_scope()
        if start is None:
            raise RunnerError(
                "task-producing recovery requires at least one task-scoped Stage"
            )
        state = self.context.state
        state.workflow_position = start
        state.task_step = 0
        if result is not None:
            self.context.set_stage("workflow_restart", result.output)
        self.context.save_state()
        return tuple(self.workflow[start:])

    def restart_target_produces_tasks(self, target: str | None) -> bool:
        position = self._target_position(target)
        return stage_result_kind(self.workflow[position]) == "tasks"

    def restart(
        self,
        target: str | None,
        result: StageResult,
    ) -> tuple[dict[str, Any], ...]:
        position = self._target_position(target)
        state = self.context.state

        if self.workflow[position].get("scope") == "task":
            start = self.task_block_start(position)
            state.workflow_position = start
            state.task_step = position - start
            position = start
        else:
            state.workflow_position = position
            state.task_step = 0

        self.context.set_stage("workflow_restart", result.output)
        self.context.save_state()
        return tuple(self.workflow[position:])

    def _target_position(self, target: str | None) -> int:
        resolved = target or next(iter(self.positions), "")
        if resolved not in self.positions:
            raise ValueError(
                f"restart target is not a top-level Stage: {resolved}"
            )
        return self.positions[resolved]


__all__ = ["LinearRouting"]
