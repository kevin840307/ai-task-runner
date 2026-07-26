#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
root = Path.cwd()
state_dir = Path(os.environ["SESSION_TEST_STATE_DIR"])
state_dir.mkdir(parents=True, exist_ok=True)
is_qwen = "-p" in args
prompt_arg = args[args.index("-p") + 1] if is_qwen else args[-1]
stdin_prompt = sys.stdin.read() if is_qwen else ""
prompt = "\n".join(part for part in (stdin_prompt, prompt_arg) if part).strip()


def count(name: str) -> int:
    path = state_dir / f"{name}.count"
    value = int(path.read_text() or "0") if path.exists() else 0
    path.write_text(str(value + 1))
    return value + 1


session = "old-session"
if "Plan only the remaining work" in prompt:
    answer = {
        "tasks": [{
            "title": "Create marker",
            "description": "Create done.txt",
            "acceptance_criteria": ["done.txt exists"],
        }]
    }
elif "Execute only the current task" in prompt:
    attempt = count("execute")
    has_old_session = (
        (is_qwen and "--resume" in args and args[args.index("--resume") + 1] == "old-session")
        or (not is_qwen and "--session" in args and args[args.index("--session") + 1] == "old-session")
    )
    if attempt == 1 and has_old_session:
        print("session not found")
        raise SystemExit(7)
    session = "new-session"
    (root / "done.txt").write_text("done", encoding="utf-8")
    answer = "created done.txt"
elif "Review only" in prompt:
    session = "new-session"
    answer = {
        "completed": (root / "done.txt").exists(),
        "reason": "checked",
        "missing_items": [],
    }
elif "fresh independent session" in prompt:
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
    print(json.dumps({"type": "session", "sessionID": session}))
    print(json.dumps({"type": "message", "part": {"type": "text", "text": text}}))
