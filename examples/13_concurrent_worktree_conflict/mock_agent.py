#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--demo-mode", required=True, choices=("task-a", "task-b", "recovery"))
    parser.add_argument("--sleep", type=float, default=0.0)
    args, _unknown = parser.parse_known_args()
    _prompt = sys.stdin.read()
    root = Path.cwd()

    if args.sleep > 0:
        time.sleep(args.sleep)

    shared = root / "shared.txt"
    if args.demo_mode == "task-a":
        shared.write_text("TASK-A\n", encoding="utf-8")
        result = "Task A wrote shared.txt"
    elif args.demo_mode == "task-b":
        shared.write_text("TASK-B\n", encoding="utf-8")
        result = "Task B wrote shared.txt"
    else:
        patches = sorted((root / ".ai-task-runner" / "ui" / "merge-recovery").glob("*.patch"))
        if not patches:
            raise SystemExit("merge recovery patch not found")
        patch = patches[-1].read_text(encoding="utf-8", errors="replace")
        current = shared.read_text(encoding="utf-8", errors="replace") if shared.exists() else ""
        if "TASK-A" not in current:
            raise SystemExit("latest target content was not present in recovery worktree")
        if "TASK-B" not in patch:
            raise SystemExit("Task B intent was not present in recovery patch")
        shared.write_text("TASK-A\nTASK-B\n", encoding="utf-8")
        result = "Recovered conflict by preserving Task A and applying Task B"

    session = "demo-" + args.demo_mode
    print(json.dumps([
        {"type": "system", "subtype": "session_start", "session_id": session},
        {
            "type": "result",
            "subtype": "success",
            "session_id": session,
            "result": result,
        },
    ]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
