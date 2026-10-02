"""Minimal durable Workflow state machine."""

from __future__ import annotations

import json
from typing import Any

from ..config.defaults import MAX_VALIDATOR_OUTPUT_CHARS
from ..errors import ConfigurationError
from ..utils import bounded_text
from .dynamic_expansion import activate_dynamic_task, dynamic_done_target, expand_stage_result
from .results import finish_run, finish_task
from .registry import create_stage
from .stages import StageContext, StageExecutor, StageResult


def _is_review_definition(definition: dict[str, Any]) -> bool:
    return (
        definition.get("type", "base") == "base"
        and definition.get("profile") == "review"
    )


class FlowEngine:
    """Run Stage -> Result -> Route until completion or stop.

    Workflow semantics are intentionally small:
    - PASS defaults to the next Stage.
    - FAIL defaults to stop unless routes.fail overrides it.
    - ERROR is not graph-routable: StageExecutor applies retry policy.
    - Review with a finite local error_policy is fail-soft: exhausted ERROR skips to next.
    - routes may override PASS/FAIL with next/done/stop/or another Stage.
    - any Stage may return tasks/stages; Runner inserts the durable child Workflow
      immediately after that Stage and resumes the parent flow when children finish.

    Technical retry/session recovery belongs only to StageExecutor.
    """

    def __init__(self, context: StageContext) -> None:
        self.context = context
        self.workflow = (
            list(context.state.expanded_workflow)
            if context.state.expanded_workflow
            else list(context.config.workflow)
        )
        self._reindex()

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
            previous, stopped = self._run_stage(position, executor, previous)
            if stopped:
                return 1

        if not state.completed and state.workflow_position >= len(self.workflow):
            finish_run(self.context)
            self.context.save_state()
        return 0

    def _run_stage(
        self,
        index: int,
        executor: StageExecutor,
        previous: StageResult | None,
    ) -> tuple[StageResult, bool]:
        definition = self.workflow[index]
        activate_dynamic_task(self.context.state, definition)
        result = self._review_bypass_result(definition)
        if result is None:
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
            self._record_review_result(definition, result)
        self._remember_previous(result)

        target = (
            resolve_handoff_target(definition, result)
            if definition.get("type") == "handoff" and result.status == "pass"
            else resolve_stage_target(definition, result.status)
        )

        expanded = expand_stage_result(
            state=self.context.state,
            workflow=self.workflow,
            source_index=index,
            source=definition,
            result=result,
            continuation=target,
        )
        if expanded is not None:
            self.workflow = expanded
            self._reindex()
            self.context.state.workflow_position = index + 1
            self.context.save_state()
            return result, False

        if (
            result.status == "pass"
            and definition.get("_dynamic_task_complete")
        ):
            finish_task(self.context)

        target = self._dynamic_target(definition, target)
        if target == "stop":
            self.context.save_state()
            return result, True
        if target == "done":
            finish_run(self.context)
            self.context.save_state()
            return result, False
        if target == "next":
            self.context.state.workflow_position = index + 1
            self.context.save_state()
            return result, False

        self._route_to(target, index, result)
        self.context.save_state()
        return result, False

    def _review_failure_key(self, definition: dict[str, Any]) -> str:
        task = self.context.task
        scope = task.id if task is not None else "__run__"
        return f"{definition['name']}::{scope}"

    def _review_bypass_result(
        self,
        definition: dict[str, Any],
    ) -> StageResult | None:
        """Skip Review execution on the entry after max_failures consecutive FAILs.

        max_failures=3 means three real semantic FAIL verdicts are allowed.
        On the fourth entry to that Review Stage, Runner does not call the
        reviewer; it emits a fail-soft PASS and clears the durable counter.
        """
        if not _is_review_definition(definition):
            return None
        maximum = definition.get("max_failures")
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
            return None

        key = self._review_failure_key(definition)
        counters = self.context.state.review_failures
        count = counters.get(key, 0)
        if count < maximum:
            return None

        counters.pop(key, None)
        data = {
            "completed": True,
            "reason": (
                f"Review fail-soft PASS on entry after {count} consecutive semantic FAIL "
                f"results (max_failures={maximum})."
            ),
            "missing_items": [],
            "fail_soft": True,
            "failure_count": count,
            "bypassed": True,
        }
        task = self.context.task
        if task is not None:
            task.last_review = data
        self.context.set_stage(
            "reviewing",
            f"Review bypass after {count} consecutive FAIL results; max_failures={maximum}",
        )
        return StageResult(
            stage=str(definition["name"]),
            status="pass",
            output=(
                f"Review fail-soft PASS without reviewer execution after {count} "
                f"consecutive FAIL results; max_failures={maximum}."
            ),
            data=data,
            kind="review",
        )

    def _record_review_result(
        self,
        definition: dict[str, Any],
        result: StageResult,
    ) -> None:
        """Persist consecutive semantic Review FAIL count; PASS resets it."""
        if not _is_review_definition(definition) or result.status not in {"pass", "fail"}:
            return
        maximum = definition.get("max_failures")
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
            return

        key = self._review_failure_key(definition)
        counters = self.context.state.review_failures
        if result.status == "pass":
            counters.pop(key, None)
            return
        counters[key] = counters.get(key, 0) + 1

    def _route_to(self, target: str, source_index: int, result: StageResult) -> None:
        position = self.positions[target]
        state = self.context.state

        if position <= source_index:
            state.cycle += 1

        state.workflow_position = position
        self.context.set_stage("workflow_route", result.output)

    def _dynamic_target(self, definition: dict[str, Any], target: str) -> str:
        if target == "done":
            nested = dynamic_done_target(definition)
            if nested is not None:
                return nested
        if target == "next" and definition.get("_dynamic_continue"):
            return str(definition["_dynamic_continue"])
        return target

    def _reindex(self) -> None:
        self.positions = {
            str(item["name"]): index
            for index, item in enumerate(self.workflow)
        }

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
    """Resolve semantic routing while keeping technical ERROR off the graph.

    Review is intentionally a local, fail-soft gate. A finite Stage-local
    error_policy means retry this many times, then skip Review so an
    unavailable reviewer cannot stop a 24H run. Other Stage types fail closed
    after their technical retry budget is exhausted. retries=-1 does not
    normally exhaust and therefore does not reach the skip path.
    """
    if status == "error":
        policy = definition.get("error_policy")
        retries = policy.get("retries") if isinstance(policy, dict) else None
        if (
            _is_review_definition(definition)
            and isinstance(retries, int)
            and not isinstance(retries, bool)
            and retries >= 0
        ):
            return "next"
        return "stop"
    routes = definition.get("routes")
    if isinstance(routes, dict) and status in routes:
        return str(routes[status])
    return "next" if status == "pass" else "stop"


def build_flow_engine(context: StageContext) -> FlowEngine:
    return FlowEngine(context)


__all__ = ["FlowEngine", "build_flow_engine", "resolve_handoff_target", "resolve_stage_target"]
