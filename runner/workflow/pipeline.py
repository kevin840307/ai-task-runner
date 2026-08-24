"""Execute plain flow definitions (dict = Stage, list = nested flow)."""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from .stages import StageContext, StageExecutor, StageResult
from .stages.factory import create_stage


class Pipeline:
    def __init__(self, context: StageContext, flow: Iterable[object]) -> None:
        self.context = context
        self.flow = list(flow)

    def run(self, executor: StageExecutor, *, plan_only: bool = False) -> int:
        flow = list(self.flow)
        previous_result: StageResult | None = None
        while flow and not self.context.state.completed:
            replacement_flow, previous_result, stop = self._run_flow(
                flow, executor, plan_only, previous_result
            )
            if stop or replacement_flow is None:
                return 0
            flow = list(replacement_flow)
        return 0

    def _run_flow(self, flow, executor, plan_only, previous_result):
        for item in flow:
            if isinstance(item, (list, tuple, deque)):
                replacement_flow, previous_result, stop = self._run_flow(
                    item, executor, plan_only, previous_result
                )
                if replacement_flow is not None or stop:
                    return replacement_flow, previous_result, stop
                continue
            if not isinstance(item, dict):
                raise TypeError(f"flow item must be dict or list, got {type(item).__name__}")

            stage = create_stage(item)
            result = executor.run(stage, self.context, previous_result)
            if result.complete:
                self.context.state.completed = True
            self.context.save_state()

            if plan_only and getattr(stage, "plan_only_stop", False) and result.status == "pass":
                return None, result, True
            if result.replace_remaining:
                return result.next_flow, result, False
            if result.next_flow:
                replacement_flow, nested_previous, stop = self._run_flow(
                    result.next_flow, executor, plan_only, result
                )
                previous_result = nested_previous or result
                if replacement_flow is not None or stop:
                    return replacement_flow, previous_result, stop
            else:
                previous_result = result
            if self.context.state.completed:
                return None, previous_result, True
        return None, previous_result, False


def build_pipeline(context: StageContext) -> Pipeline:
    from .rules import initial_flow
    return Pipeline(context, initial_flow(context))


__all__ = ["Pipeline", "build_pipeline"]
