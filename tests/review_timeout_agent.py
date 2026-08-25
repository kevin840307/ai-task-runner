#!/usr/bin/env python3
"""Fake CLI whose first review call hangs longer than planning timeout."""
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
state_dir = Path(os.environ["REVIEW_TIMEOUT_STATE_DIR"])
state_dir.mkdir(parents=True, exist_ok=True)
session = "review-timeout-session"
prompt_kind = prompt_stage(prompt)

if prompt_kind in {"plan_finalize", "plan_refine"}:
    stage = prompt_kind
    answer = {
        "tasks": [{
            "title": "Create marker",
            "description": "Create done.txt",
            "deliverable": "done.txt exists",
            "acceptance_criteria": ["done.txt exists"],
            "steps": ["execute", "review"],
        }]
    }
elif prompt_kind == "plan_judge":
    stage = "plan_judge"
    n = max(1, prompt.count('"title"'))
    answer = {"accepted": True, "issues": []}
elif prompt_kind == "execute":
    stage = "execute"
    (root / "done.txt").write_text("done", encoding="utf-8")
    answer = "created done.txt"
elif prompt_kind == "review":
    stage = "review"
    answer = {
        "completed": (root / "done.txt").exists(),
        "reason": "checked",
        "missing_items": [],
    }
elif prompt_kind == "validator":
    stage = "validator"
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
if stage == "review" and count == 0:
    print("review started", flush=True)
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
