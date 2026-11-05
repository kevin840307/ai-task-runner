#!/usr/bin/env python3
"""Deterministic fake agent for concurrent Runner/worktree conflict recovery tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fake_agent_io import prompt_stage, read_prompt

args = sys.argv[1:]
root = Path.cwd()
is_qwen, prompt = read_prompt(args)
stage = prompt_stage(prompt)


def _case_marker(text: str) -> str:
    if "TASK_C_RECOVERY" in text:
        return "TASK_C_RECOVERY"
    if "TASK_B_RECOVERY" in text:
        return "TASK_B_RECOVERY"
    if "Merge-repair task only" in text:
        if "TASK_C" in text:
            return "TASK_C_RECOVERY"
        if "TASK_B" in text:
            return "TASK_B_RECOVERY"
    if "TASK_A" in text:
        return "TASK_A"
    if "TASK_B" in text:
        return "TASK_B"
    if "TASK_C" in text:
        return "TASK_C"
    return ""


marker = _case_marker(prompt)

if stage in {"plan_finalize", "plan_refine"}:
    if not marker:
        raise SystemExit(7)
    title = {
        "TASK_A": "TASK_A_WRITE",
        "TASK_B": "TASK_B_WRITE",
        "TASK_C": "TASK_C_WRITE",
        "TASK_B_RECOVERY": "TASK_B_RECOVERY",
        "TASK_C_RECOVERY": "TASK_C_RECOVERY",
    }[marker]
    answer = {
        "tasks": [{
            "title": title,
            "description": title,
            "deliverable": "app.txt contains the expected integrated content",
            "acceptance_criteria": ["app.txt contains the expected integrated content"],
        }]
    }
elif stage == "plan_judge":
    answer = {"accepted": True, "issues": []}
elif stage == "execute":
    if "TASK_C_RECOVERY" in prompt:
        current = (root / "app.txt").read_text(encoding="utf-8")
        if current != "task-a + task-b\n":
            print(f"unexpected TASK_C recovery base: {current!r}", file=sys.stderr)
            raise SystemExit(11)
        (root / "app.txt").write_text("task-a + task-b + task-c\n", encoding="utf-8")
        answer = "ported TASK_C onto the latest TASK_A + TASK_B target"
    elif "TASK_B_RECOVERY" in prompt:
        current = (root / "app.txt").read_text(encoding="utf-8")
        if current != "task-a\n":
            print(f"unexpected TASK_B recovery base: {current!r}", file=sys.stderr)
            raise SystemExit(8)
        (root / "app.txt").write_text("task-a + task-b\n", encoding="utf-8")
        answer = "ported TASK_B onto the latest TASK_A target"
    elif "TASK_A_WRITE" in prompt:
        (root / "app.txt").write_text("task-a\n", encoding="utf-8")
        answer = "wrote TASK_A"
    elif "TASK_B_WRITE" in prompt:
        (root / "app.txt").write_text("task-b\n", encoding="utf-8")
        answer = "wrote TASK_B"
    elif "TASK_C_WRITE" in prompt:
        (root / "app.txt").write_text("task-c\n", encoding="utf-8")
        answer = "wrote TASK_C"
    else:
        print("unknown execute case", file=sys.stderr)
        raise SystemExit(9)
elif stage in {"review", "review_finalize"}:
    content = (root / "app.txt").read_text(encoding="utf-8") if (root / "app.txt").is_file() else ""
    completed = content in {
        "task-a\n",
        "task-b\n",
        "task-c\n",
        "task-a + task-b\n",
        "task-a + task-b + task-c\n",
    }
    answer = {
        "completed": completed,
        "reason": "deterministic integration check",
        "missing_items": [] if completed else ["expected app.txt content"],
    }
elif stage == "validator":
    content = (root / "app.txt").read_text(encoding="utf-8") if (root / "app.txt").is_file() else ""
    passed = content in {
        "task-a\n",
        "task-b\n",
        "task-c\n",
        "task-a + task-b\n",
        "task-a + task-b + task-c\n",
    }
    answer = {
        "passed": passed,
        "reason": "deterministic validator",
        "missing_items": [] if passed else ["expected app.txt content"],
    }
else:
    print(f"unsupported stage: {stage}", file=sys.stderr)
    raise SystemExit(10)

text = json.dumps(answer) if isinstance(answer, dict) else answer
session = "conflict-validator-session" if stage == "validator" else "conflict-runner-session"
if is_qwen:
    print(json.dumps([
        {"type": "system", "subtype": "session_start", "session_id": session},
        {"type": "result", "subtype": "success", "session_id": session, "result": text},
    ]))
else:
    print(json.dumps({"type": "step_start", "sessionID": session, "part": {"type": "step-start"}}))
    print(json.dumps({"type": "text", "sessionID": session, "part": {"type": "text", "text": text}}))
    print(json.dumps({
        "type": "step_finish",
        "sessionID": session,
        "part": {
            "type": "step-finish",
            "tokens": {"input": 1, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}},
        },
    }))
