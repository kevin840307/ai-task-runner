#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

root = Path.cwd()
variant = os.environ.get("CONCURRENT_DEMO_VARIANT", "").strip().upper()
prompt = sys.stdin.read()
args = sys.argv[1:]
resume = args[args.index("--resume") + 1] if "--resume" in args else ""
session = resume or f"demo-{variant.lower() or 'unknown'}-session"

if variant == "A":
    (root / "app.txt").write_text(
        "base\n"
        "task-a: enabled\n",
        encoding="utf-8",
    )
    answer = "Task A updated app.txt"
elif variant == "B":
    (root / "app.txt").write_text(
        "base\n"
        "task-b: enabled\n",
        encoding="utf-8",
    )
    answer = "Task B updated app.txt"
elif variant == "RECOVERY":
    # The recovery workspace is based on the latest target, which already
    # contains Task A. Preserve that content and integrate Task B.
    current = (root / "app.txt").read_text(encoding="utf-8")
    if "task-a: enabled" not in current:
        print(
            json.dumps([
                {
                    "type": "system",
                    "subtype": "session_start",
                    "session_id": session,
                },
                {
                    "type": "result",
                    "subtype": "error",
                    "session_id": session,
                    "result": "recovery workspace did not contain latest target",
                },
            ])
        )
        raise SystemExit(3)
    if "task-b: enabled" not in current:
        current = current.rstrip() + "\ntask-b: enabled\n"
    (root / "app.txt").write_text(current, encoding="utf-8")
    answer = "Conflict recovery preserved Task A and integrated Task B"
else:
    answer = f"Unknown demo variant: {variant}"
    print(
        json.dumps([
            {
                "type": "system",
                "subtype": "session_start",
                "session_id": session,
            },
            {
                "type": "result",
                "subtype": "error",
                "session_id": session,
                "result": answer,
            },
        ])
    )
    raise SystemExit(2)

print(
    json.dumps([
        {
            "type": "system",
            "subtype": "session_start",
            "session_id": session,
        },
        {
            "type": "result",
            "subtype": "success",
            "session_id": session,
            "result": answer,
        },
    ])
)
