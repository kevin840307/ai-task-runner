#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from fake_agent_io import prompt_stage, read_prompt  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--demo-mode", required=True, choices=("task-a", "task-b", "recovery"))
    parser.add_argument("--sleep", type=float, default=0.0)
    args, unknown = parser.parse_known_args()
    is_qwen, prompt = read_prompt(unknown)
    stage = prompt_stage(prompt)
    root = Path.cwd()

    if args.sleep > 0:
        time.sleep(args.sleep)

    target = root / "shared.txt"
    expected_values = {"TASK-A\n", "TASK-B\n", "TASK-A\nTASK-B\n"}

    if stage in {"plan_finalize", "plan_refine"}:
        title = {
            "task-a": "TASK_A_WRITE",
            "task-b": "TASK_B_WRITE",
            "recovery": "TASK_B_RECOVERY",
        }[args.demo_mode]
        answer = {
            "tasks": [{
                "title": title,
                "description": title,
                "deliverable": "shared.txt contains the expected demo content",
                "acceptance_criteria": ["shared.txt contains the expected demo content"],
                "steps": ["execute", "review"],
            }]
        }
    elif stage == "plan_judge":
        answer = {"accepted": True, "issues": []}
    elif stage == "execute":
        if args.demo_mode == "task-a":
            target.write_text("TASK-A\n", encoding="utf-8")
            answer = "Task A wrote shared.txt"
        elif args.demo_mode == "task-b":
            target.write_text("TASK-B\n", encoding="utf-8")
            answer = "Task B wrote shared.txt"
        else:
            patches = sorted(
                (root / ".ai-task-runner" / "ui" / "merge-recovery").glob("*.patch")
            )
            if not patches:
                raise SystemExit("merge recovery patch not found")
            patch = patches[-1].read_text(encoding="utf-8", errors="replace")
            current = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
            if current != "TASK-A\n":
                raise SystemExit(f"unexpected recovery base: {current!r}")
            if "TASK-B" not in patch:
                raise SystemExit("Task B intent was not present in recovery patch")
            target.write_text("TASK-A\nTASK-B\n", encoding="utf-8")
            answer = "Recovered conflict by preserving Task A and applying Task B"
    elif stage in {"review", "review_finalize"}:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        completed = current in expected_values
        answer = {
            "completed": completed,
            "reason": "deterministic concurrent-worktree demo review",
            "missing_items": [] if completed else ["expected shared.txt content"],
        }
    elif stage == "validator":
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        passed = current in expected_values
        answer = {
            "passed": passed,
            "reason": "deterministic concurrent-worktree demo validator",
            "missing_items": [] if passed else ["expected shared.txt content"],
        }
    else:
        raise SystemExit(f"unsupported Runner stage: {stage}")

    text = json.dumps(answer) if isinstance(answer, dict) else str(answer)
    session = "demo-validator-session" if stage == "validator" else f"demo-{args.demo_mode}-session"
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
