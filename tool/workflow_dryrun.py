#!/usr/bin/env python3
"""Dry-run the real minimal Workflow engine with deterministic Stage results."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.runtime.run_state import RunState, Task, set_stage
from runner.workflow.flow_engine import FlowEngine
from runner.workflow.loader import load_workflow
from runner.workflow.results import reduce_result
from runner.workflow.registry import stage_result_kind
from runner.workflow.stages import StageResult


class DryRunLimit(RuntimeError):
    pass


class MockAIClient:
    def __init__(self) -> None:
        self.session_id = "dryrun-session"


class DryRunContext:
    def __init__(self, root: Path, workflow: list[dict[str, Any]]) -> None:
        self.root = root
        self.work = root / ".dryrun"
        self.work.mkdir(parents=True, exist_ok=True)
        self.config = SimpleNamespace(
            workflow=workflow,
            ai_validator_prompt="dry-run",
            max_cycles=-1,
        )
        self.state = RunState(
            run_id="dryrun",
            goal="Validate Workflow closure.",
            project_root=str(root),
        )
        self.ai_client = MockAIClient()
        self.state_file = self.work / "state.json"
        self.validator_path = None
        self.validator_is_ai = True
        self.scratch: dict[str, Any] = {}

    def save_state(self) -> None:
        pass

    def set_stage(self, stage: str, detail: str = "") -> None:
        set_stage(self.state, stage, detail)

    def save_session(self) -> None:
        self.state.ai_session_id = self.ai_client.session_id

    def reset_sessions(self) -> None:
        self.ai_client.session_id = ""
        self.state.ai_session_id = ""

    @property
    def task(self) -> Task | None:
        return (
            self.state.tasks[self.state.current]
            if self.state.current < len(self.state.tasks)
            else None
        )

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
        self.counts: dict[tuple[str, str], int] = defaultdict(int)

    @staticmethod
    def _normalize(value: Any) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            raise ValueError("scenario stages/labels must be objects")
        result: dict[str, list[str]] = {}
        for key, raw in value.items():
            values = raw if isinstance(raw, list) else [raw]
            statuses = [str(item).lower() for item in values]
            if any(item not in {"pass", "fail", "error"} for item in statuses):
                raise ValueError(f"invalid dry-run status for {key}")
            result[str(key)] = statuses
        return result

    def next(self, stage: str, label: str) -> str:
        if label in self.labels:
            return self._pick("label", label, self.labels[label])
        if stage in self.stages:
            return self._pick("stage", stage, self.stages[stage])
        if self.default not in {"pass", "fail", "error"}:
            raise ValueError(f"invalid default dry-run status: {self.default}")
        return self.default

    def _pick(self, kind: str, key: str, values: list[str]) -> str:
        token = (kind, key)
        index = self.counts[token]
        self.counts[token] += 1
        return values[min(index, len(values) - 1)]


class MockStageExecutor:
    def __init__(self, scenario: Scenario, max_steps: int) -> None:
        self.scenario = scenario
        self.max_steps = max_steps
        self.calls = 0
        self.trace: list[tuple[int, str, str, str]] = []

    def run(
        self,
        stage,
        ctx: DryRunContext,
        previous=None,
        *,
        label: str = "",
        retry_limit: int | None = None,
    ) -> StageResult:
        self.calls += 1
        if self.calls > self.max_steps:
            raise DryRunLimit(
                f"workflow did not converge within {self.max_steps} Stage executions"
            )
        status = self.scenario.next(stage.name, label)
        result = stage.finish(ctx, self._result(stage, ctx, status))
        produces = str(getattr(getattr(stage, "spec", None), "produces", "") or "")
        kind = produces or str(getattr(stage, "result_kind", "generic") or "generic")
        if result.kind != kind:
            result = replace(result, kind=kind)
        result = reduce_result(ctx, result)
        self.trace.append((self.calls, stage.name, label, result.status))
        return result

    def _result(self, stage, ctx: DryRunContext, status: str) -> StageResult:
        if status == "error":
            return StageResult.error_result(stage.name, RuntimeError("simulated error"))

        kind = str(getattr(stage, "result_kind", "generic") or "generic")
        produces = str(getattr(getattr(stage, "spec", None), "produces", "") or "")
        kind = produces or kind
        if kind == "tasks":
            if status == "fail":
                return StageResult(stage.name, "fail", output="TASKS_FAIL")
            task = Task(
                id=f"c{ctx.state.cycle:02d}-t001",
                title="Dry-run task",
                description="Exercise task-scoped routing.",
                acceptance_criteria=["Workflow closes."],
            )
            return StageResult(stage.name, "pass", output="TASKS_PASS", data=[task])
        if kind == "handoff":
            if status == "fail":
                return StageResult(stage.name, "fail", output="HANDOFF_FAIL", kind="handoff")
            targets = list(getattr(getattr(stage, "spec", None), "targets", []) or [])
            if not targets:
                return StageResult.error_result(
                    stage.name, RuntimeError("handoff has no targets")
                )
            target = targets[-1]
            return StageResult(
                stage.name,
                "pass",
                output="HANDOFF",
                data={"target": target, "reason": "dry-run"},
                kind="handoff",
            )

        return StageResult(stage.name, status, output=status.upper())


def load_scenario(path: Path | None) -> Scenario:
    if path is None:
        return Scenario()
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("scenario must be a YAML object")
    return Scenario(data)


def _execute(
    workflow: list[dict[str, Any]],
    scenario: Scenario,
    max_steps: int,
) -> tuple[DryRunContext, MockStageExecutor, str]:
    temporary = tempfile.TemporaryDirectory(prefix="ai-task-runner-dryrun-")
    ctx = DryRunContext(Path(temporary.name), workflow)
    ctx.scratch["_temporary"] = temporary
    executor = MockStageExecutor(scenario, max_steps)
    error = ""
    try:
        FlowEngine(ctx).run(executor)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return ctx, executor, error


def _close(ctx: DryRunContext) -> None:
    temporary = ctx.scratch.pop("_temporary", None)
    if temporary is not None:
        temporary.cleanup()


@dataclass(frozen=True)
class MatrixCase:
    name: str
    scenario: Scenario
    expected_completed: bool


def _matrix_cases(workflow: list[dict[str, Any]]) -> list[MatrixCase]:
    cases = [MatrixCase("happy path", Scenario(), True)]
    for definition in workflow:
        name = str(definition["name"])
        routes = definition.get("routes") or {}
        for status in ("fail", "error"):
            target = str(routes.get(status, "stop"))
            if target == "stop":
                cases.append(
                    MatrixCase(
                        f"{name} {status.upper()} -> stop",
                        Scenario({"stages": {name: status}}),
                        False,
                    )
                )
            else:
                cases.append(
                    MatrixCase(
                        f"{name} {status.upper()} -> {target} -> closure",
                        Scenario({"stages": {name: [status, "pass"]}}),
                        True,
                    )
                )
    return cases


def matrix_payload(path: Path, max_steps: int) -> dict[str, Any]:
    workflow = load_workflow(path)
    results = []
    for case in _matrix_cases(workflow):
        ctx, executor, error = _execute(workflow, case.scenario, max_steps)
        try:
            completed = bool(ctx.state.completed) and not error
            results.append({
                "name": case.name,
                "passed": not error and completed is case.expected_completed,
                "completed": completed,
                "expected_completed": case.expected_completed,
                "executions": executor.calls,
                "error": error or None,
            })
        finally:
            _close(ctx)

    passed = sum(bool(item["passed"]) for item in results)
    return {
        "valid": True,
        "closed": passed == len(results),
        "workflow": str(path),
        "features": {
            "stages": len(workflow),
            "task_scope": any(item.get("scope") == "task" for item in workflow),
            "task_producer": any(stage_result_kind(item) == "tasks" for item in workflow),
            "routes": sum(bool(item.get("routes")) for item in workflow),
            "file_validations": sum(
                item.get("type") == "command"
                and stage_result_kind(item) == "validation"
                for item in workflow
            ),
            "ai_validations": sum(
                item.get("type") == "ai_validator"
                for item in workflow
            ),
            "validation_not_last": any(
                stage_result_kind(item) == "validation"
                and index < len(workflow) - 1
                for index, item in enumerate(workflow)
            ),
        },
        "paths_passed": passed,
        "paths_total": len(results),
        "cases": results,
    }


def run_dryrun(
    path: Path,
    scenario_path: Path | None,
    max_steps: int,
    *,
    json_output: bool = False,
) -> int:
    workflow = load_workflow(path)
    scenario = load_scenario(scenario_path)
    ctx, executor, error = _execute(workflow, scenario, max_steps)
    try:
        completed = bool(ctx.state.completed) and not error
        if json_output:
            print(json.dumps({
                "valid": True,
                "completed": completed,
                "workflow": str(path),
                "executions": executor.calls,
                "error": error or None,
                "transitions": [
                    {
                        "number": number,
                        "stage": stage,
                        "label": label or None,
                        "status": status,
                    }
                    for number, stage, label, status in executor.trace
                ],
            }, ensure_ascii=False, indent=2))
        else:
            for number, stage, label, status in executor.trace:
                display = f"{stage} [{label}]" if label else stage
                print(f"{number:03d}  {display:<48} {status.upper()}")
            print("DRYRUN_PASSED" if completed else f"DRYRUN_FAILED {error}")
        return 0 if completed else 1
    finally:
        _close(ctx)


def run_matrix(path: Path, max_steps: int, *, json_output: bool = False) -> int:
    payload = matrix_payload(path, max_steps)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in payload["cases"]:
            print(f"{'PASS' if item['passed'] else 'FAIL'} {item['name']}")
        print(
            "WORKFLOW_CLOSED"
            if payload["closed"]
            else "WORKFLOW_NOT_CLOSED"
        )
    return 0 if payload["closed"] else 1


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Validate Stage result-edge Workflow closure with mock results."
    )
    value.add_argument("workflow", type=Path)
    value.add_argument("--scenario", type=Path)
    value.add_argument("--max-steps", type=int, default=100)
    value.add_argument("--matrix", action="store_true")
    value.add_argument("--json", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.max_steps < 1:
        return 2
    try:
        workflow = args.workflow.resolve()
        if args.matrix:
            if args.scenario:
                return 2
            return run_matrix(workflow, args.max_steps, json_output=args.json)
        return run_dryrun(
            workflow,
            args.scenario.resolve() if args.scenario else None,
            args.max_steps,
            json_output=args.json,
        )
    except Exception as exc:
        print(f"DRYRUN_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
