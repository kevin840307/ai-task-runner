#!/usr/bin/env python3
"""Fake CLI that writes task output then hangs before returning."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from fake_agent_io import prompt_stage, read_prompt

args = sys.argv[1:]
root = Path.cwd()
is_qwen, prompt = read_prompt(args)
state_dir = Path(os.environ["IDLE_AFTER_CHANGE_STATE_DIR"])
state_dir.mkdir(parents=True, exist_ok=True)
session = "idle-main-session"
stage = prompt_stage(prompt)


def count(name: str) -> int:
    path = state_dir / f"{name}.count"
    value = int(path.read_text(encoding="utf-8")) if path.exists() else 0
    path.write_text(str(value + 1), encoding="utf-8")
    return value


if stage in {"plan_finalize", "plan_refine"}:
    count("plan")
    answer = {
        "tasks": [{
            "title": "Create marker",
            "description": "Create done.txt",
            "deliverable": "done.txt exists",
            "acceptance_criteria": ["done.txt exists"],
            "steps": ["execute", "review"],
        }]
    }
elif stage == "plan_judge":
    count("judge")
    n = max(1, prompt.count('"title"'))
    answer = {"accepted": True, "issues": []}
elif stage == "execute":
    count("execute")
    (root / "done.txt").write_text("done", encoding="utf-8")
    time.sleep(30)
    answer = "created done.txt"
elif stage == "review":
    count("review")
    answer = {
        "completed": (root / "done.txt").exists(),
        "reason": "checked",
        "missing_items": [],
    }
elif stage == "validator":
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
    print(json.dumps({"type": "step_start", "sessionID": session, "part": {"type": "step-start"}}))
    print(json.dumps({"type": "text", "sessionID": session, "part": {"type": "text", "text": text}}))
    print(json.dumps({"type": "step_finish", "sessionID": session, "part": {"type": "step-finish", "tokens": {"input": 1, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}}}}))
