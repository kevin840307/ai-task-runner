#!/usr/bin/env python3
"""Fake Qwen/OpenCode CLI that times out once in every model stage."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from fake_agent_io import read_prompt

args = sys.argv[1:]
root = Path.cwd()
is_qwen, prompt = read_prompt(args)
state_dir = Path(os.environ["TIMEOUT_STAGE_STATE_DIR"])
state_dir.mkdir(parents=True, exist_ok=True)
session = "timeout-main-session"

if "Plan only the remaining work" in prompt or "independent plan editor" in prompt:
    stage = "plan_refine" if "independent plan editor" in prompt else "plan"
    answer = {
        "tasks": [{
            "title": "Create marker",
            "description": "Create done.txt",
            "deliverable": "done.txt exists",
            "acceptance_criteria": ["done.txt exists"],
        }]
    }
elif "plan quality judge" in prompt:
    stage = "plan_judge"
    n = max(1, prompt.count('"title"'))
    answer = {"accepted": True, "issues": []}
elif "Execute only the current task" in prompt or "Complete only the current TODO" in prompt:
    stage = "execute"
    (root / "done.txt").write_text("done", encoding="utf-8")
    answer = "created done.txt"
elif "Review only" in prompt:
    stage = "review"
    answer = {
        "completed": (root / "done.txt").exists(),
        "reason": "checked",
        "missing_items": [],
    }
elif "fresh independent session" in prompt:
    stage = "validator"
    session = "timeout-validator-session"
    answer = {
        "passed": (root / "done.txt").exists(),
        "reason": "checked",
        "missing_items": [],
    }
else:
    raise SystemExit(2)

counter = state_dir / f"{stage}.count"
count = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(count + 1), encoding="utf-8")
if count == 0 and stage != "plan_refine":
    print(f"{stage} started", flush=True)
    time.sleep(30)

text = json.dumps(answer) if isinstance(answer, dict) else answer
if is_qwen:
    print(json.dumps([
        {"type": "system", "subtype": "session_start", "session_id": session},
        {"type": "result", "subtype": "success", "session_id": session, "result": text},
    ]))
else:
    print(json.dumps({"type": "session", "sessionID": session}))
    print(json.dumps({"type": "message", "part": {"type": "text", "text": text}}))
