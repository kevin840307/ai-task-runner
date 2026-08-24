#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

from fake_agent_io import prompt_stage, read_prompt, record_prompt

args = sys.argv[1:]
root = Path.cwd()
is_qwen, prompt = read_prompt(args)
session = "scenario-session-001"
scenario = os.environ.get("SCENARIO", "")
state_dir = Path(os.environ["SCENARIO_STATE_DIR"])
state_dir.mkdir(parents=True, exist_ok=True)
stage = prompt_stage(prompt)
record_prompt(state_dir, stage, prompt, args)


def count(name):
    path = state_dir / f"{name}.count"
    value = int(path.read_text() or "0") if path.exists() else 0
    path.write_text(str(value + 1))
    return value + 1


if stage in {"plan_finalize", "plan_refine"}:
    if scenario == "multi_task_plan":
        answer = {"tasks": [
            {"title": "Create first marker", "description": "Create first.txt", "deliverable": "first.txt exists", "acceptance_criteria": ["first.txt exists"]},
            {"title": "Create second marker", "description": "Create second.txt after first.txt", "deliverable": "second.txt exists", "acceptance_criteria": ["second.txt exists"]},
        ]}
    else:
        answer = {"tasks": [{"title": "Create marker", "description": "Create done.txt", "deliverable": "done.txt exists", "acceptance_criteria": ["done.txt exists"]}]}
elif stage == "plan_judge":
    n = max(1, prompt.count('"title"'))
    answer = {"accepted": True, "issues": []}
elif stage == "execute":
    n = count("execute")
    if scenario == "multi_task_plan":
        log = state_dir / "order.log"
        if '"title": "Create second marker"' in prompt:
            if not (root / "first.txt").exists():
                print("second ran before first")
                raise SystemExit(7)
            (root / "second.txt").write_text("second", encoding="utf-8")
            with log.open("a", encoding="utf-8") as handle:
                handle.write("execute:second\n")
        elif '"title": "Create first marker"' in prompt:
            (root / "first.txt").write_text("first", encoding="utf-8")
            log.write_text("execute:first\n", encoding="utf-8")
        else:
            print("unknown task")
            raise SystemExit(7)
        answer = "execution finished"
    else:
        answer = "execution finished"
    if scenario == "execution_model_error" and n <= 3:
        print("stable tool failure")
        raise SystemExit(7)
    if scenario == "api_503" and n <= 3:
        print("HTTP 503 Service Unavailable")
        raise SystemExit(7)
    if scenario == "loop_detection" and n == 1:
        print("Loop detection halted the run (consecutive_identical_tool_calls)")
        raise SystemExit(7)
    if scenario == "execution_model_error_no_change_forever":
        print("stable tool failure without project changes")
        raise SystemExit(7)
    if scenario == "execution_error_after_change":
        (root / "done.txt").write_text("done", encoding="utf-8")
        print("failed after writing")
        raise SystemExit(7)
    if scenario == "protected_retry" and n == 1:
        Path(os.environ["PROTECTED_PATH"]).write_text("changed", encoding="utf-8")
    if scenario == "validator_repair" and "Validator repair mode" in prompt:
        (root / "repaired.txt").write_text("done", encoding="utf-8")
    if scenario != "stagnation" and scenario != "multi_task_plan":
        (root / "done.txt").write_text("done", encoding="utf-8")
elif stage == "review":
    n = count("review")
    if scenario == "multi_task_plan":
        log = state_dir / "order.log"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(
                "review:second\n"
                if '"title": "Create second marker"' in prompt
                else "review:first\n"
            )
        completed = (
            (root / "first.txt").exists() and (root / "second.txt").exists()
            if '"title": "Create second marker"' in prompt
            else (root / "first.txt").exists()
        )
        answer = {"completed": completed, "reason": "checked", "missing_items": [] if completed else ["missing marker"]}
    else:
        if scenario == "readonly" and n == 1:
            (root / "review_mutation.txt").write_text("should be restored", encoding="utf-8")
        if scenario == "review_non_json":
            answer = "The task is complete, but this review is not JSON."
        elif scenario == "stagnation":
            completed = n >= 4
            missing = [] if completed else ["same missing item"]
            answer = {"completed": completed, "reason": "checked", "missing_items": missing}
        else:
            completed = not (scenario == "review_retry" and n == 1)
            missing = [] if completed else ["retry once"]
            answer = {"completed": completed, "reason": "checked", "missing_items": missing}
elif stage == "validator":
    n = count("validator")
    session = "scenario-validator-session-001"
    if scenario == "readonly" and n == 1:
        (root / "validator_mutation.txt").write_text("should be restored", encoding="utf-8")
    passed = not (
        (scenario == "ai_replan" and n == 1)
        or (scenario == "ai_replan_many" and n <= 4)
    )
    answer = {"passed": passed, "reason": "checked", "missing_items": [] if passed else ["retry cycle"]}
else:
    raise SystemExit(2)

text = json.dumps(answer) if isinstance(answer, dict) else answer
if is_qwen:
    print(json.dumps([
        {"type": "system", "subtype": "session_start", "session_id": session},
        {"type": "result", "subtype": "success", "session_id": session, "result": text},
    ]))
else:
    print(json.dumps({"type": "session", "sessionID": session}))
    print(json.dumps({"type": "message", "part": {"type": "text", "text": text}}))
