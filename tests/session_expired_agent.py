#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

from fake_agent_io import prompt_stage, read_prompt

args = sys.argv[1:]
root = Path.cwd()
state_dir = Path(os.environ["SESSION_TEST_STATE_DIR"])
state_dir.mkdir(parents=True, exist_ok=True)
is_qwen, prompt = read_prompt(args)
stage = prompt_stage(prompt)


def count(name: str) -> int:
    path = state_dir / f"{name}.count"
    value = int(path.read_text() or "0") if path.exists() else 0
    path.write_text(str(value + 1))
    return value + 1


session = "old-session"
if stage in {"plan_finalize", "plan_refine"}:
    answer = {
        "tasks": [{
            "title": "Create marker",
            "description": "Create done.txt",
            "deliverable": "done.txt exists",
            "acceptance_criteria": ["done.txt exists"],
        }]
    }
elif stage == "plan_judge":
    n = max(1, prompt.count('"title"'))
    answer = {"accepted": True, "issues": []}
elif stage == "execute":
    attempt = count("execute")
    has_old_session = (
        (is_qwen and "--resume" in args and args[args.index("--resume") + 1] == "old-session")
        or (not is_qwen and "--session" in args and args[args.index("--session") + 1] == "old-session")
    )
    if attempt == 1:
        # First technical failure still exposes a durable session. StageExecutor
        # must retry this same Stage by resuming old-session.
        if is_qwen:
            print(json.dumps({
                "type": "system",
                "subtype": "session_start",
                "session_id": "old-session",
            }))
        else:
            print(json.dumps({
                "type": "step_start",
                "sessionID": "old-session",
                "part": {"type": "step-start"},
            }))
        print("HTTP 503 Service Unavailable", file=sys.stderr)
        raise SystemExit(7)
    if attempt == 2 and has_old_session:
        message = os.environ.get("SESSION_FAILURE_MESSAGE", "session not found")
        if is_qwen:
            print(json.dumps({
                "type": "result",
                "subtype": "error",
                "session_id": "old-session",
                "error": {"message": message},
            }))
        else:
            print(message, file=sys.stderr)
        raise SystemExit(7)
    if attempt < 3:
        print("expected old-session resume before fresh recovery", file=sys.stderr)
        raise SystemExit(8)
    session = "new-session"
    (root / "done.txt").write_text("done", encoding="utf-8")
    answer = "created done.txt"
elif stage == "review":
    session = "new-session"
    answer = {
        "completed": (root / "done.txt").exists(),
        "reason": "checked",
        "missing_items": [],
    }
elif stage == "validator":
    session = "validator-session"
    answer = {
        "passed": (root / "done.txt").exists(),
        "reason": "checked",
        "missing_items": [],
    }
else:
    raise SystemExit(2)

text = json.dumps(answer) if isinstance(answer, dict) else answer
if is_qwen:
    print(json.dumps([
        {"type": "system", "subtype": "session_start", "session_id": session},
        {"type": "result", "subtype": "success", "session_id": session, "result": text},
    ]))
else:
    print(json.dumps({"type": "step_start", "sessionID": session, "part": {"type": "step-start"}}))
    print(json.dumps({"type": "text", "sessionID": session, "part": {"type": "text", "text": text}}))
    print(json.dumps({"type": "step_finish", "sessionID": session, "part": {"type": "step-finish", "tokens": {"input": 1, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}}}}))
