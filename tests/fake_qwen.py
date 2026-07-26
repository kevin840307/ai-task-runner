#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
prompt = sys.argv[sys.argv.index("-p") + 1]; root = Path.cwd()
if "split the remaining work" in prompt:
    cycle2 = '"cycle": 2' in prompt
    if cycle2:
        print(json.dumps({"tasks":[{"title":"Repair final result","description":"Create task-002.done","acceptance_criteria":["task-002.done exists"]}]}))
    else:
        print(json.dumps({"tasks":[{"title":"First","description":"Create task-001.done","acceptance_criteria":["exists"]},{"title":"Second","description":"Create task-002.done","acceptance_criteria":["exists"]}]}))
elif "Execute ONLY" in prompt:
    if '"task_index": 0' in prompt: (root/"task-001.done").write_text("done")
    else: (root/"task-002.done").write_text("done")
    print("implemented")
elif "Independently inspect" in prompt:
    target = "task-001.done" if '"task_index": 0' in prompt else "task-002.done"
    ok = (root/target).exists(); print(json.dumps({"completed":ok,"reason":"checked","missing_items":[] if ok else ["missing"]}))
else: raise SystemExit(2)
