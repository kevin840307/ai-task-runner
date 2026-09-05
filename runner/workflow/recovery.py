"""Small recovery decision layer shared by Pipeline routing."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol

from .stages import StageContext, StageExecutor, StageResult

RecoveryKind = Literal["next", "recover", "restart", "replan", "stop"]


class RecoveryNode(Protocol):
    stage: object
    recover: tuple[dict, ...]
    restart_at: str | None
    repeat: int | None
    fresh_after_same_failures: int | None
    scope: str
    workflow_index: int | None


@dataclass(frozen=True)
class RecoveryAction:
    kind: RecoveryKind
    limit_reached: bool = False


class RecoveryPolicy:
    """Classify semantic Stage results without owning Pipeline control flow."""

    def __init__(self, context: StageContext) -> None:
        self.context = context

    def pending_recovery(self, node: RecoveryNode) -> StageResult | None:
        repeat = node.repeat
        if repeat is None:
            return None
        state = self.context.state
        if (
            state.flow_result_key != self._key(node)
            or state.flow_result_count < repeat
            or not state.flow_result_previous
        ):
            return None
        saved = state.flow_result_previous
        return StageResult(
            str(saved.get("stage", getattr(node.stage, "name", "stage"))),
            "fail",
            output=str(saved.get("output", "")),
            data=saved.get("data"),
        )

    def decide(
        self,
        node: RecoveryNode,
        result: StageResult,
        executor: StageExecutor,
    ) -> RecoveryAction:
        limit_reached = self._record_repeat(node, result)
        self._observe_semantic_failure(node, result, executor)

        if result.status == "replan":
            return RecoveryAction("replan", limit_reached)
        if result.status == "fail" and node.restart_at is not None:
            return RecoveryAction("restart", limit_reached)
        if result.status == "fail" and node.recover:
            return RecoveryAction("recover", limit_reached)
        if result.status in {"fail", "error"}:
            return RecoveryAction("stop", limit_reached)

        if result.status == "pass":
            self.clear_repeat(node)
            self.clear_semantic_failure(node)
        return RecoveryAction("next", limit_reached)

    def clear_repeat(self, node: RecoveryNode) -> None:
        if node.repeat is None:
            return
        state = self.context.state
        if state.flow_result_key == self._key(node):
            state.flow_result_key = ""
            state.flow_result_count = 0
            state.flow_result_previous = {}

    def clear_semantic_failure(self, node: RecoveryNode) -> None:
        if self._semantic_threshold(node) is None:
            return
        state = self.context.state
        if state.semantic_failure_key == self._key(node):
            state.semantic_failure_key = ""
            state.semantic_failure_fingerprint = ""
            state.semantic_failure_count = 0
            self.context.save_state()

    def _record_repeat(self, node: RecoveryNode, result: StageResult) -> bool:
        repeat = node.repeat
        if repeat is None or result.status not in {"pass", "fail"}:
            return False
        state = self.context.state
        key = self._key(node)
        if state.flow_result_key != key:
            state.flow_result_key = key
            state.flow_result_count = 0
        state.flow_result_count += 1
        if result.status == "fail":
            state.flow_result_previous = {
                "stage": result.stage,
                "status": result.status,
                "output": result.output,
                "data": json.loads(
                    json.dumps(result.data, ensure_ascii=False, default=str)
                ),
            }
        self.context.save_state()
        return result.status == "fail" and state.flow_result_count >= repeat

    def _observe_semantic_failure(
        self,
        node: RecoveryNode,
        result: StageResult,
        executor: StageExecutor,
    ) -> None:
        threshold = self._semantic_threshold(node)
        if threshold is None or result.status != "fail":
            return
        state = self.context.state
        key = self._key(node)
        fingerprint = self._fingerprint(result)
        if (
            state.semantic_failure_key != key
            or state.semantic_failure_fingerprint != fingerprint
        ):
            state.semantic_failure_key = key
            state.semantic_failure_fingerprint = fingerprint
            state.semantic_failure_count = 1
        else:
            state.semantic_failure_count += 1
        self.context.save_state()
        if state.semantic_failure_count >= threshold:
            executor.fresh_session(node.stage, self.context)
            self.clear_semantic_failure(node)

    @staticmethod
    def _semantic_threshold(node: RecoveryNode) -> int | None:
        if node.fresh_after_same_failures is not None:
            return node.fresh_after_same_failures
        if not node.recover:
            return None
        value = getattr(node.stage, "semantic_failure_threshold", None)
        return int(value) if value is not None else None

    def _key(self, node: RecoveryNode) -> str:
        task = getattr(self.context, "task", None)
        if task is None:
            state = self.context.state
            tasks = getattr(state, "tasks", ())
            current = int(getattr(state, "current", 0))
            task = tasks[current] if 0 <= current < len(tasks) else None
        stage_name = str(getattr(node.stage, "name", "stage"))
        if node.scope == "task" and task is not None:
            return f"task:{task.id}:{stage_name}"
        if node.workflow_index is not None:
            return f"workflow:{node.workflow_index}"
        spec = getattr(node.stage, "spec", None)
        prompt = getattr(spec, "prompt", "")
        return f"stage:{stage_name}:{prompt}"

    @staticmethod
    def _fingerprint(result: StageResult) -> str:
        value = result.data if result.data is not None else result.output

        def normalize(item):
            if isinstance(item, dict):
                return {str(key): normalize(item[key]) for key in sorted(item)}
            if isinstance(item, list):
                return [normalize(value) for value in item]
            if isinstance(item, str):
                return " ".join(item.split())
            return item

        payload = json.dumps(
            normalize(value), ensure_ascii=False, sort_keys=True, default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["RecoveryAction", "RecoveryPolicy"]
