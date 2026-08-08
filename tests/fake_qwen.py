#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
prompt = sys.stdin.read(); root = Path.cwd()
if "Plan only the remaining work" in prompt or "independent plan editor" in prompt:
    cycle2 = '"cycle": 2' in prompt
    if cycle2:
        print(json.dumps({"tasks":[{"title":"Repair final result","description":"Create task-002.done","deliverable":"task-002.done exists","acceptance_criteria":["task-002.done exists"]}]}))
    else:
        print(json.dumps({"tasks":[{"title":"First","description":"Create task-001.done","deliverable":"task-001.done exists","acceptance_criteria":["exists"]},{"title":"Second","description":"Create task-002.done","deliverable":"task-002.done exists","acceptance_criteria":["exists"]}]}))
elif "plan quality judge" in prompt:
    count = max(1, prompt.count('"title"'))
    print(json.dumps({"accepted": True, "issues": []}))
elif "Execute only the current task" in prompt or "Complete only the current TODO" in prompt:
    if '"task_index": 0' in prompt: (root/"task-001.done").write_text("done")
    else: (root/"task-002.done").write_text("done")
    print("implemented")
elif "Review only" in prompt:
    target = "task-001.done" if '"task_index": 0' in prompt else "task-002.done"
    ok = (root/target).exists(); print(json.dumps({"completed":ok,"reason":"checked","missing_items":[] if ok else ["missing"]}))
else: raise SystemExit(2)
