#!/usr/bin/env python3
"""Run exactly one Workflow Stage, report its result and resolved next target, then stop."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.config.defaults import DEFAULT_BACKEND
from runner.config.runtime import RuntimeConfig
from runner.bootstrap import runtime_scope
from runner.runtime.run_state import Task
from runner.workflow.flow_engine import resolve_handoff_target, resolve_stage_target
from runner.workflow.loader import load_workflow, normalize_workflow
from runner.workflow.registry import create_stage
from runner.workflow.stages import BaseStage, StageResult
from runner.workflow_runner import WorkflowRunner

AGENT_PING_TIMEOUT_SECONDS = 60
STAGE_TEST_UNLIMITED_RETRY_CAP = 2


class _MockErrorOnceStage:
    """Stage-test-only wrapper that injects one deterministic technical ERROR."""

    def __init__(self, stage) -> None:
        self._stage = stage
        self._injected = False

    def __getattr__(self, name):
        return getattr(self._stage, name)

    def run(self, ctx, previous=None):
        if not self._injected:
            self._injected = True
            return StageResult.error_result(
                self._stage.name,
                RuntimeError("MOCK_STAGE_TEST_ERROR: injected recoverable technical failure"),
            )
        return self._stage.run(ctx, previous)

    def finish(self, ctx, result):
        return self._stage.finish(ctx, result)
AGENT_PING_PROMPT = (
    "Reply with exactly AGENT_PING_OK and nothing else. "
    "Do not use tools, do not modify files, and do not inspect the project."
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Execute one Workflow Stage only")
    value.add_argument("--project-root", required=True)
    value.add_argument("--workflow", required=True)
    value.add_argument("--stage", required=True)
    value.add_argument("--input", default="")
    value.add_argument("--request-stdin", action="store_true")
    value.add_argument("--backend", default="")
    value.add_argument("--command", default="")
    value.add_argument("--probe-mode", choices=("stage", "agent_ping"), default="stage")
    value.add_argument("--keep-work", action="store_true")
    return value


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return str(value)


def _resolved_next(workflow: list[dict[str, Any]], index: int, result: StageResult) -> str:
    definition = workflow[index]
    target = (
        resolve_handoff_target(definition, result)
        if definition.get("type") == "handoff" and result.status == "pass"
        else resolve_stage_target(definition, result.status)
    )
    if target == "next":
        return str(workflow[index + 1]["name"]) if index + 1 < len(workflow) else "done"
    return target


def _draft_next(
    draft: dict[str, Any],
    stage_name: str,
    result: StageResult,
) -> tuple[str, str]:
    definition = draft["stages"][stage_name]
    if definition.get("type") == "handoff" and result.status == "pass":
        target = resolve_handoff_target(
            {"name": stage_name, **definition},
            result,
        )
        return target, "handoff"
    route = resolve_stage_target(definition, result.status)
    if route != "next":
        return route, route
    flow = draft.get("flow") or []
    index = flow.index(stage_name) if stage_name in flow else -1
    return (str(flow[index + 1]) if index >= 0 and index + 1 < len(flow) else "done"), route


def _agent_ping(client, timeout: int | float) -> tuple[str, float]:
    """Call the configured backend once with a fixed no-tool transport probe."""
    client.session_id = ""
    client.set_runtime("no_tool", allow_project_read=False, sandbox=False)
    started = time.monotonic()
    output = client.ask(
        AGENT_PING_PROMPT,
        timeout=min(AGENT_PING_TIMEOUT_SECONDS, max(1, int(timeout))),
    )
    return output, time.monotonic() - started


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    project = Path(args.project_root).expanduser().resolve()
    workflow_path = Path(args.workflow).expanduser().resolve()
    if not project.is_dir():
        raise ValueError("project root does not exist")
    if not workflow_path.is_file():
        raise ValueError("workflow does not exist")

    draft_workflow = getattr(args, "draft_workflow", None)
    if draft_workflow is not None:
        if not isinstance(draft_workflow, dict) or not isinstance(draft_workflow.get("stages"), dict) or args.stage not in draft_workflow["stages"]:
            raise ValueError(f"unknown Workflow Stage: {args.stage}")
        draft_for_test = {
            "stages": dict(draft_workflow["stages"]),
            "flow": list(draft_workflow.get("flow") or []),
        }
        if args.stage not in draft_for_test["flow"]:
            draft_for_test["flow"].append(args.stage)
        workflow = normalize_workflow(draft_for_test, workflow_path)
    else:
        workflow = load_workflow(workflow_path)
        if not any(str(item["name"]) == args.stage for item in workflow):
            import yaml
            source = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
            if args.stage not in source.get("stages", {}):
                raise ValueError(f"unknown Workflow Stage: {args.stage}")
            source["flow"] = [*source["flow"], args.stage]
            workflow = normalize_workflow(source, workflow_path)
    index = next((i for i, item in enumerate(workflow) if str(item["name"]) == args.stage), -1)
    if index < 0:
        raise ValueError(f"unknown Workflow Stage: {args.stage}")

    definition = workflow[index]
    stage = create_stage(definition)
    test_id = uuid.uuid4().hex[:12]
    work_dir = f".ai-task-runner/stage-tests/{test_id}"
    input_text = str(args.input or "").strip()
    goal = input_text or f"Test Workflow Stage {args.stage}"

    probe_mode = str(getattr(args, "probe_mode", "stage") or "stage")
    test_scenario = str(getattr(args, "test_scenario", "pass") or "pass")
    configured_command = getattr(args, "command", None)
    config = RuntimeConfig(
        goal=goal,
        project_root=str(project),
        backend=str(args.backend or DEFAULT_BACKEND),
        workflow=workflow,
        workflow_explicit=True,
        command=(
            configured_command
            if configured_command
            else None
            if probe_mode == "agent_ping" or isinstance(stage, BaseStage)
            else sys.executable
        ),
        work_dir=work_dir,
        force_new=True,
        stage_retries=0,
        auto_register_ui_project=False,
        human_output=False,
    )
    config.validate()
    try:
        with runtime_scope(config):
            runner = WorkflowRunner(config)

            if probe_mode == "agent_ping":
                output, elapsed = _agent_ping(runner.context.ai_client, config.agent_timeout)
                return {
                    "ok": True,
                    "stage": args.stage,
                    "status": "pass",
                    "output": output,
                    "data": {
                        "prompt": AGENT_PING_PROMPT,
                        "backend": config.backend,
                        "elapsed_seconds": round(elapsed, 3),
                    },
                    "changed_files": [],
                    "next": "not-run",
                    "route": "agent_ping",
                    "kind": "agent_ping",
                    "work_dir": str((project / work_dir).resolve()),
                }

            if (
                str(definition.get("type") or "base") == "base"
                and str(definition.get("profile") or "generic") in {"execute", "review"}
            ):
                runner.state.tasks = [
                    Task(
                        id="stage-test",
                        title=f"Test {args.stage}",
                        description=input_text or f"Execute the selected Stage {args.stage} once.",
                        acceptance_criteria=["Return the Stage result for this isolated test."],
                    )
                ]
                runner._save_state()

            previous = (
                StageResult(
                    "__test_input__",
                    "pass",
                    output=input_text,
                    data={"input": input_text},
                )
                if input_text
                else None
            )

            policy = definition.get("error_policy")
            configured_retry = policy.get("retries") if isinstance(policy, dict) else None
            if configured_retry == -1:
                retry_limit = STAGE_TEST_UNLIMITED_RETRY_CAP
                retry_policy = f"test_cap:{STAGE_TEST_UNLIMITED_RETRY_CAP}"
            elif isinstance(configured_retry, int) and not isinstance(configured_retry, bool):
                retry_limit = configured_retry
                retry_policy = f"local:{configured_retry}"
            else:
                retry_limit = 0
                retry_policy = "single_attempt_default"
            stage_under_test = _MockErrorOnceStage(stage) if test_scenario == "error_mock" else stage
            result = runner.stage_executor.run(
                stage_under_test,
                runner.context,
                previous,
                retry_limit=retry_limit,
            )
            next_target, route = _draft_next(draft_workflow, args.stage, result) if draft_workflow is not None else (
                _resolved_next(workflow, index, result), resolve_stage_target(definition, result.status)
            )
            return {
                "ok": result.status != "error",
                "stage": args.stage,
                "status": result.status,
                "output": result.output,
                "data": result.data,
                "changed_files": result.changed_files,
                "next": next_target,
                "route": route,
                "kind": result.kind,
                "work_dir": str((project / work_dir).resolve()),
                "test_retry_limit": retry_limit,
                "test_retry_policy": retry_policy,
                "test_scenario": test_scenario,
                "mock_error_injected": test_scenario == "error_mock",
            }
    finally:
        if not args.keep_work:
            shutil.rmtree(project / work_dir, ignore_errors=True)
            current = project / ".ai-task-runner" / "stage-tests"
            try:
                current.rmdir()
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.request_stdin:
            request = json.load(sys.stdin)
            if not isinstance(request, dict):
                raise ValueError("Stage test request must be an object")
            args.input = str(request.get("input") or "")
            args.draft_workflow = request.get("workflow")
            args.probe_mode = str(request.get("probe_mode") or "stage")
            if args.probe_mode not in {"stage", "agent_ping"}:
                raise ValueError("Stage test probe_mode must be stage or agent_ping")
            args.test_scenario = str(request.get("test_scenario") or "pass")
            if args.test_scenario not in {"pass", "fail", "error_mock"}:
                raise ValueError("Stage test test_scenario must be pass, fail, or error_mock")
        payload = run_probe(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, default=_json_default))
    return 0 if payload["status"] != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
