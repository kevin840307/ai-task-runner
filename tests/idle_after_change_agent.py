#!/usr/bin/env python3
"""Fake CLI that writes task output then hangs before returning."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
root = Path.cwd()
is_qwen = "-p" in args
prompt_arg = args[args.index("-p") + 1] if is_qwen else args[-1]
stdin_prompt = sys.stdin.read() if is_qwen else ""
prompt = "\n".join(part for part in (stdin_prompt, prompt_arg) if part).strip()
state_dir = Path(os.environ["IDLE_AFTER_CHANGE_STATE_DIR"])
state_dir.mkdir(parents=True, exist_ok=True)
session = "idle-main-session"


def count(name: str) -> int:
    path = state_dir / f"{name}.count"
    value = int(path.read_text(encoding="utf-8")) if path.exists() else 0
    path.write_text(str(value + 1), encoding="utf-8")
    return value


if "Plan only the remaining work" in prompt:
    count("plan")
    answer = {
        "tasks": [{
            "title": "Create marker",
            "description": "Create done.txt",
            "acceptance_criteria": ["done.txt exists"],
        }]
    }
elif "Execute only the current task" in prompt:
    count("execute")
    (root / "done.txt").write_text("done", encoding="utf-8")
    time.sleep(30)
    answer = "created done.txt"
elif "Review only" in prompt:
    count("review")
    answer = {
        "completed": (root / "done.txt").exists(),
        "reason": "checked",
        "missing_items": [],
    }
elif "fresh independent session" in prompt:
    count("validator")
    session = "idle-validator-session"
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
