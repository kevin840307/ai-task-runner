#!/usr/bin/env python3
"""Dry-run a real workflow YAML with deterministic mock Stage results.

This tool intentionally lives outside runner Core. It reuses the real workflow
loader, Pipeline, StageResult, Stage.finish(), and durable reducers while
replacing only Stage execution with deterministic mock results.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.runtime.run_state import RunState, Task, set_stage
from runner.workflow.loader import load_workflow
from runner.workflow.pipeline import Pipeline
from runner.workflow.stages import StageResult


class DryRunLimit(RuntimeError):
    pass


class MockAIClient:
    def __init__(self) -> None:
        self.session_id = "dryrun-session-1"


class DryRunContext:
    """Minimum StageContext-compatible object required by the real Pipeline."""

    def __init__(self, root: Path, flow: list[dict[str, Any]]) -> None:
        self.root = root
        self.work = root / ".dryrun"
        self.work.mkdir(parents=True, exist_ok=True)
        self.ai_client = MockAIClient()
        self.config = SimpleNamespace(
            workflow=flow,
            max_cycles=1000,
            ai_validator_prompt="dry-run",
        )
        self.state = RunState(
            run_id="dryrun",
            goal="Validate workflow closure with deterministic mock results.",
            project_root=str(root),
        )
        self.state_file = self.work / "state.json"
        self.validator_path = None
        self.validator_is_ai = True
        self.scratch: dict[str, Any] = {}
        self.saved = 0

    def save_state(self) -> None:
        self.saved += 1

    def set_stage(self, stage: str, detail: str = "") -> None:
        set_stage(self.state, stage, detail)

    def save_session(self) -> None:
        self.state.ai_session_id = self.ai_client.session_id
        self.save_state()

    def reset_sessions(self) -> None:
        self.ai_client.session_id = ""
        self.state.ai_session_id = ""
        self.save_state()

    @property
    def task(self) -> Task | None:
        if self.state.current < len(self.state.tasks):
            return self.state.tasks[self.state.current]
        return None

    def require_task(self, stage: str) -> Task:
        task = self.task
        if task is None:
            raise RuntimeError(f"{stage} stage requires a pending task")
        return task


class Scenario:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        self.default = str(data.get("default", "pass")).lower()
        self.stages = self._normalize(data.get("stages", {}))
        self.labels = self._normalize(data.get("labels", {}))
        self.plan_steps = [str(item) for item in data.get("plan_steps", [])]
        self._counts: dict[tuple[str, str], int] = defaultdict(int)

    @staticmethod
    def _normalize(value: Any) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            raise ValueError("scenario stages/labels must be YAML objects")
        result: dict[str, list[str]] = {}
        for key, raw in value.items():
            items = raw if isinstance(raw, list) else [raw]
            statuses = [str(item).lower() for item in items]
            if not statuses or any(item not in {"pass", "fail", "error"} for item in statuses):
                raise ValueError(f"invalid dry-run result sequence for {key}")
            result[str(key)] = statuses
        return result

    def next(self, stage: str, label: str) -> str:
        if label and label in self.labels:
            return self._pick("label", label, self.labels[label])
        if stage in self.stages:
            return self._pick("stage", stage, self.stages[stage])
        if self.default not in {"pass", "fail", "error"}:
            raise ValueError(f"invalid default dry-run result: {self.default}")
        return self.default

    def _pick(self, kind: str, key: str, values: list[str]) -> str:
        counter_key = (kind, key)
        index = self._counts[counter_key]
        self._counts[counter_key] += 1
        return values[min(index, len(values) - 1)]


class MockStageExecutor:
    """StageExecutor-shaped adapter that returns deterministic StageResult values."""

    def __init__(self, scenario: Scenario, *, max_steps: int) -> None:
        self.scenario = scenario
        self.max_steps = max_steps
        self.trace: list[tuple[int, str, str, str]] = []
        self.fresh_sessions: list[str] = []
        self.calls = 0

    def run(self, stage, ctx: DryRunContext, previous=None, *, label: str = "") -> StageResult:
        self.calls += 1
        if self.calls > self.max_steps:
            raise DryRunLimit(f"workflow did not converge within {self.max_steps} Stage executions")

        status = self.scenario.next(stage.name, label)
        raw = self._result(stage, ctx, status)
        result = stage.finish(ctx, raw)
        self.trace.append((self.calls, stage.name, label, result.status))
        return result

    def fresh_session(self, stage, ctx: DryRunContext) -> None:
        token = f"dryrun-session-{len(self.fresh_sessions) + 2}"
        self.fresh_sessions.append(stage.name)
        ctx.ai_client.session_id = token
        ctx.state.ai_session_id = token
        ctx.save_state()

    def _result(self, stage, ctx: DryRunContext, status: str) -> StageResult:
        if status == "error":
            return StageResult.error_result(stage.name, RuntimeError("simulated dry-run error"))

        spec = getattr(stage, "spec", None)
        planner_stages = getattr(spec, "planner_stages", None)
        if planner_stages:
            if status == "fail":
                return StageResult(stage.name, "fail", output="simulated planning failure")
            tasks = [self._plan_task(ctx, planner_stages)]
            return StageResult(stage.name, "pass", output="DRYRUN_PLAN", data=tasks)

        handler = getattr(spec, "result_handler", None)
        handler_name = getattr(handler, "__name__", "")
        if handler_name == "handle_review_result":
            completed = status == "pass"
            return StageResult(
                stage.name,
                status,
                output="DRYRUN_REVIEW_PASS" if completed else "DRYRUN_REVIEW_FAIL",
                data={
                    "completed": completed,
                    "reason": "dry-run deterministic result",
                    "missing_items": [] if completed else ["simulated missing item"],
                },
            )
        if handler_name == "handle_validation_result" or getattr(spec, "validator", None):
            passed = status == "pass"
            return StageResult(
                stage.name,
                status,
                output="DRYRUN_VALIDATION_PASS" if passed else "DRYRUN_VALIDATION_FAIL",
                data={"passed": passed, "reason": "dry-run deterministic result"},
            )
        return StageResult(stage.name, status, output=f"DRYRUN_{status.upper()}")

    def _plan_task(self, ctx: DryRunContext, planner_stages: dict[str, dict[str, Any]]) -> Task:
        steps = list(self.scenario.plan_steps)
        if not steps:
            write = [
                name for name, definition in planner_stages.items()
                if definition.get("mode") == "write"
            ]
            review = [
                name for name, definition in planner_stages.items()
                if definition.get("result_handler") == "review"
            ]
            if write:
                steps.append(write[0])
            if review and review[0] not in steps:
                steps.append(review[0])
            if not steps:
                steps.append(next(iter(planner_stages)))
        unknown = [name for name in steps if name not in planner_stages]
        if unknown:
            raise ValueError(f"scenario plan_steps contains unavailable Stage: {unknown[0]}")
        return Task(
            id=f"c{ctx.state.cycle:02d}-t001",
            title="Dry-run task",
            description="Exercise generated workflow routing.",
            deliverable="Dry-run only",
            acceptance_criteria=["Workflow reaches closure."],
            steps=steps,
        )


def load_scenario(path: Path | None) -> Scenario:
    if path is None:
        return Scenario()
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("scenario must be a YAML object")
    return Scenario(data)


def _execute(flow: list[dict[str, Any]], scenario: Scenario, max_steps: int) -> tuple[DryRunContext, MockStageExecutor, str]:
    temporary = tempfile.TemporaryDirectory(prefix="ai-task-runner-dryrun-")
    ctx = DryRunContext(Path(temporary.name), flow)
    ctx.scratch["_temporary"] = temporary
    executor = MockStageExecutor(scenario, max_steps=max_steps)
    error = ""
    try:
        Pipeline(ctx, flow).run(executor)
    except DryRunLimit as exc:
        error = str(exc)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return ctx, executor, error


def _close_context(ctx: DryRunContext) -> None:
    temporary = ctx.scratch.pop("_temporary", None)
    if temporary is not None:
        temporary.cleanup()


def _print_result(workflow_path: Path, scenario_path: Path | None, flow: list[dict[str, Any]], ctx: DryRunContext, executor: MockStageExecutor, error: str) -> int:
    print(f"Workflow: {workflow_path}")
    if scenario_path:
        print(f"Scenario: {scenario_path}")
    print("\nTransitions:")
    for number, stage, label, status in executor.trace:
        display = f"{stage} [{label}]" if label else stage
        print(f"{number:03d}  {display:<48} {status.upper()}")
    if executor.fresh_sessions:
        print("\nFresh sessions:")
        for stage in executor.fresh_sessions:
            print(f"- {stage}")

    closed = bool(ctx.state.completed)
    print("\nResult:")
    print(f"completed={str(closed).lower()}")
    print(f"stage={ctx.state.stage}")
    print(f"workflow_position={ctx.state.workflow_position}/{len(flow)}")
    print(f"executions={executor.calls}")
    if error:
        print(f"error={error}")
    if closed and not error:
        print("DRYRUN_PASSED")
        return 0
    print("DRYRUN_FAILED")
    return 1


def _walk_definitions(flow: list[dict[str, Any]]):
    seen: set[tuple[str, str]] = set()

    def visit(definition: dict[str, Any], source: str):
        key = (source, str(definition.get("name", "")))
        if key in seen:
            return
        seen.add(key)
        yield definition, source
        for nested in definition.get("recover", ()):
            yield from visit(nested, source)
        for name, nested in definition.get("planner_stages", {}).items():
            yield from visit(nested, f"plan:{definition.get('name')}:{name}")

    for definition in flow:
        yield from visit(definition, "flow")


def _matrix_cases(flow: list[dict[str, Any]]) -> list[tuple[str, Scenario]]:
    cases: list[tuple[str, Scenario]] = [("happy path", Scenario())]
    added: set[str] = set()
    for definition, source in _walk_definitions(flow):
        name = str(definition.get("name", ""))
        if not name or not definition.get("recover") or name in added:
            continue
        added.add(name)
        data: dict[str, Any] = {"default": "pass", "stages": {name: ["fail", "pass"]}}
        if source.startswith("plan:"):
            data["plan_steps"] = [name]
        cases.append((f"{name} FAIL -> recover -> closure", Scenario(data)))
    return cases


def run_matrix(workflow_path: Path, max_steps: int) -> int:
    flow = load_workflow(workflow_path)
    results: list[tuple[str, bool, str, int]] = []
    print(f"Workflow Dry Run Matrix\nWorkflow: {workflow_path}\n")
    for title, scenario in _matrix_cases(flow):
        ctx, executor, error = _execute(flow, scenario, max_steps)
        try:
            passed = bool(ctx.state.completed) and not error
            results.append((title, passed, error, executor.calls))
        finally:
            _close_context(ctx)
    width = max(len(title) for title, *_ in results)
    for title, passed, error, calls in results:
        suffix = f" ({calls} executions)"
        if error:
            suffix += f" - {error}"
        print(f"{title:<{width}}  {'PASS' if passed else 'FAIL'}{suffix}")
    passed_count = sum(1 for _, passed, _, _ in results if passed)
    print(f"\n{passed_count}/{len(results)} paths converged")
    if passed_count == len(results):
        print("WORKFLOW_CLOSED")
        return 0
    print("WORKFLOW_NOT_CLOSED")
    return 1


def run_dryrun(workflow_path: Path, scenario_path: Path | None, max_steps: int) -> int:
    flow = load_workflow(workflow_path)
    scenario = load_scenario(scenario_path)
    ctx, executor, error = _execute(flow, scenario, max_steps)
    try:
        return _print_result(workflow_path, scenario_path, flow, ctx, executor, error)
    finally:
        _close_context(ctx)

def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Validate workflow.yaml closure with mock Stage results.")
    value.add_argument("workflow", type=Path, help="Workflow YAML to validate")
    value.add_argument("--scenario", type=Path, help="Optional dry-run scenario YAML")
    value.add_argument("--max-steps", type=int, default=100, help="Stop non-converging workflows after N Stage executions")
    value.add_argument("--matrix", action="store_true", help="Auto-test happy path and one FAIL/recovery path for every recoverable Stage")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.max_steps < 1:
        print("--max-steps must be >= 1", file=sys.stderr)
        return 2
    try:
        workflow = args.workflow.resolve()
        if args.matrix:
            if args.scenario:
                print("--matrix cannot be combined with --scenario", file=sys.stderr)
                return 2
            return run_matrix(workflow, args.max_steps)
        return run_dryrun(workflow, args.scenario.resolve() if args.scenario else None, args.max_steps)
    except Exception as exc:
        print(f"DRYRUN_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
