"""Minimal graph definition for composing workflow stages."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

StageTarget = str | None
TargetResolver = Callable[[Any], StageTarget]
EntryResolver = Callable[[Any], StageTarget]


@dataclass
class FlowDefinition:
    """Stage nodes plus transition routes; no workflow DSL or registry required."""

    nodes: dict[str, Any]
    transitions: dict[tuple[str, str], StageTarget | TargetResolver] = field(default_factory=dict)
    start: str | None = None
    entry_resolver: EntryResolver | None = None

    @classmethod
    def linear(cls, *stages: Any) -> "FlowDefinition":
        if not stages:
            raise ValueError("flow requires at least one stage")
        nodes = {stage.name: stage for stage in stages}
        if len(nodes) != len(stages):
            raise ValueError("flow stage names must be unique")
        flow = cls(nodes=nodes, start=stages[0].name)
        for current, following in zip(stages, stages[1:]):
            flow.route(current.name, "advance", following.name)
        flow.route(stages[-1].name, "advance", None)
        return flow

    def route(
        self,
        stage: str,
        action: str,
        target: StageTarget | TargetResolver,
    ) -> "FlowDefinition":
        if stage not in self.nodes:
            raise ValueError(f"unknown flow stage: {stage}")
        if isinstance(target, str) and target not in self.nodes:
            raise ValueError(f"unknown flow target: {target}")
        self.transitions[(stage, action)] = target
        return self

    def entry(self, context: Any) -> StageTarget:
        target = self.entry_resolver(context) if self.entry_resolver else self.start
        self._validate_target(target)
        return target

    def next(self, stage: str, action: str, context: Any) -> StageTarget:
        if stage not in self.nodes:
            raise ValueError(f"unknown flow stage: {stage}")
        route = self.transitions.get((stage, action))
        if route is None and (stage, action) not in self.transitions:
            if action == "retry":
                return stage
            if action == "replan":
                return self.start
            raise ValueError(f"missing flow route: {stage}.{action}")
        target = route(context) if callable(route) else route
        self._validate_target(target)
        return target

    def stage(self, name: str) -> Any:
        return self.nodes[name]

    def _validate_target(self, target: StageTarget) -> None:
        if target is not None and target not in self.nodes:
            raise ValueError(f"unknown flow target: {target}")


__all__ = ["FlowDefinition"]


def default_flow(planning: Any, execute: Any, review: Any, validate: Any) -> FlowDefinition:
    """Current built-in workflow expressed as a graph, not Core control flow."""
    flow = FlowDefinition.linear(planning, execute, review, validate)

    def entry(context: Any) -> StageTarget:
        state = context.state
        if state.completed:
            return None
        if state.tasks and state.current < len(state.tasks):
            return execute.name
        if state.stage == "validator_failed" or not state.tasks or not all(
            task.status == "completed" for task in state.tasks
        ):
            return planning.name
        return validate.name

    def after_review(context: Any) -> StageTarget:
        return execute.name if context.state.current < len(context.state.tasks) else validate.name

    flow.entry_resolver = entry
    flow.route(review.name, "retry", execute.name)
    flow.route(review.name, "advance", after_review)
    return flow


__all__ = ["FlowDefinition", "default_flow"]
