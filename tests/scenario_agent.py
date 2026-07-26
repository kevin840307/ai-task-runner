#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
root = Path.cwd()
is_qwen = "-p" in args
prompt = args[args.index("-p") + 1] if is_qwen else args[-1]
session = "scenario-session-001"
scenario = os.environ.get("SCENARIO", "")
state_dir = Path(os.environ["SCENARIO_STATE_DIR"])
state_dir.mkdir(parents=True, exist_ok=True)


def count(name):
    path = state_dir / f"{name}.count"
    value = int(path.read_text() or "0") if path.exists() else 0
    path.write_text(str(value + 1))
    return value + 1


if "Plan only the remaining work" in prompt:
    answer = {"tasks": [{"title": "Create marker", "description": "Create done.txt", "acceptance_criteria": ["done.txt exists"]}]}
elif "Execute only the current task" in prompt:
    n = count("execute")
    if scenario == "protected_retry" and n == 1:
        Path(os.environ["PROTECTED_PATH"]).write_text("changed", encoding="utf-8")
    if scenario == "stagnation" and "Previous attempts made no effective progress" in prompt:
        (state_dir / "strategy_seen.txt").write_text("yes", encoding="utf-8")
    if scenario != "stagnation":
        (root / "done.txt").write_text("done", encoding="utf-8")
    answer = "execution finished"
elif "Review only" in prompt:
    n = count("review")
    if scenario == "readonly" and n == 1:
        (root / "review_mutation.txt").write_text("should be restored", encoding="utf-8")
    if scenario == "stagnation":
        completed = n >= 4
        missing = [] if completed else ["same missing item"]
    else:
        completed = not (scenario == "review_retry" and n == 1)
        missing = [] if completed else ["retry once"]
    answer = {"completed": completed, "reason": "checked", "missing_items": missing}
elif "fresh independent session" in prompt:
    n = count("validator")
    session = "scenario-validator-session-001"
    if scenario == "readonly" and n == 1:
        (root / "validator_mutation.txt").write_text("should be restored", encoding="utf-8")
    passed = not (scenario == "ai_replan" and n == 1)
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
