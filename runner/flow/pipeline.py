"""Execute plain flow definitions (dict = Stage, list = nested flow)."""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any

from .stages import StageContext, StageExecutor, StageResult
from .stages.factory import create_stage

FlowItem = dict[str, Any] | list[object] | tuple[object, ...] | deque[object]


class Pipeline:
    def __init__(self, context: StageContext, flow: Iterable[object]) -> None:
        self.context = context
        self.flow = list(flow)

    def run(self, executor: StageExecutor, *, plan_only: bool = False) -> int:
        flow = list(self.flow)
        previous: StageResult | None = None
        while flow and not self.context.state.completed:
            replacement, previous, stop = self._run(flow, executor, plan_only, previous)
            if stop or replacement is None:
                return 0
            flow = list(replacement)
        return 0

    def _run(self, flow, executor, plan_only, previous):
        for item in flow:
            if isinstance(item, (list, tuple, deque)):
                replacement, previous, stop = self._run(item, executor, plan_only, previous)
                if replacement is not None or stop:
                    return replacement, previous, stop
                continue
            if not isinstance(item, dict):
                raise TypeError(f"flow item must be dict or list, got {type(item).__name__}")
            stage = create_stage(item)
            result = executor.run(stage, self.context, previous)
            if result.complete:
                self.context.state.completed = True
            self.context.save_state()
            if plan_only and getattr(stage, "plan_only_stop", False) and result.status == "pass":
                return None, result, True
            if result.replace:
                return result.stages, result, False
            if result.stages:
                replacement, nested_previous, stop = self._run(result.stages, executor, plan_only, result)
                previous = nested_previous or result
                if replacement is not None or stop:
                    return replacement, previous, stop
            else:
                previous = result
            if self.context.state.completed:
                return None, previous, True
        return None, previous, False


def build_pipeline(context: StageContext) -> Pipeline:
    from .behavior import initial_flow
    return Pipeline(context, initial_flow(context))


__all__ = ["Pipeline", "build_pipeline"]
