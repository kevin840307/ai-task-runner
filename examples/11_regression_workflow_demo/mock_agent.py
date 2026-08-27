#!/usr/bin/env python3
import json
import re
import sys
import uuid
from pathlib import Path

root = Path.cwd()
prompt = sys.stdin.read()
args = sys.argv[1:]
resume = ""
if "--resume" in args:
    resume = args[args.index("--resume") + 1]

def write(path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

def role():
    low = prompt.lower()
    if "final independent read-only validation" in low:
        return "final"
    if "read-only adversarial challenge" in low:
        return "grill"
    if "read-only review" in low:
        return "review"
    return "writer"

r = role()
if resume:
    session = resume
elif r == "final":
    session = f"final-{uuid.uuid4().hex[:12]}"
elif r == "review":
    session = "review-session"
elif r == "grill":
    session = "grill-session"
else:
    session = "writer-session"

low = prompt.lower()
if r == "writer":
    if "project discovery" in low:
        write("artifacts/project_discovery.md", "# Discovery\n- Entry: src/calculator.py\n- Operations: add, subtract, multiply, divide\n- divide by zero raises ValueError\n- unsupported operations raise ValueError\n")
    elif "project documentation" in low:
        write("artifacts/project_documentation.md", "# Project Documentation\nRun: `python smoke_test.py`\nOperations: add, subtract, multiply, divide.\nDivision by zero raises `ValueError: division by zero`.\nUnsupported operations raise `ValueError`.\n")
    elif "e2e spec generation" in low:
        write("artifacts/e2e_spec.md", "# E2E SPEC\n- add: 2,3 => 5\n- subtract: 7,2 => 5\n- multiply: 4,3 => 12\n- divide: 8,2 => 4\n- divide by zero => ValueError `division by zero`\n- unknown operation => ValueError\n")
    elif "verification design" in low:
        write("artifacts/verification_design.md", "# Verification Design\nRun smoke_test.py for core behavior. Execute every regression/cases.yaml case and compare result or expected error.\n")
    elif "regression dsl generation" in low:
        write("regression/cases.yaml", "cases:\n  - {name: add, operation: add, a: 2, b: 3, expected: 5}\n  - {name: divide, operation: divide, a: 8, b: 2, expected: 4}\n  - {name: divide-zero, operation: divide, a: 1, b: 0, error: division by zero}\n")
    elif "execution & qualification" in low:
        write("artifacts/qualification.md", "# Qualification\nChecks: `python smoke_test.py` and regression cases inspection.\nResult: PASS. Core smoke behavior passed and DSL expectations match calculator behavior.\n")
    elif "fix only the issues" in low:
        # prove previous.data reached the Fix prompt; fail loudly if not present
        if '"reason"' not in prompt or '"missing_items"' not in prompt:
            print(json.dumps([{"type":"system","subtype":"session_start","session_id":session},{"type":"result","subtype":"error","session_id":session,"result":"missing previous.data"}]))
            raise SystemExit(3)
        # Generic fix: append evidence marker to the target named by feedback.
        if "documentation" in low:
            p = root / "artifacts/project_documentation.md"
        elif "e2e" in low:
            p = root / "artifacts/e2e_spec.md"
        else:
            p = root / "artifacts/project_discovery.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((p.read_text(encoding="utf-8") if p.exists() else "") + "\nReviewed gap fixed from previous.data.\n", encoding="utf-8")
    answer = "stage completed"
elif r in {"review", "grill"}:
    # First Project Documentation grill intentionally fails, then passes after generic Fix.
    target_doc = "project_documentation.md" in low or "project documentation" in low
    if r == "grill" and target_doc:
        p = root / "artifacts/project_documentation.md"
        fixed = p.exists() and "Reviewed gap fixed" in p.read_text(encoding="utf-8")
        if not fixed:
            answer = json.dumps({"completed": False, "reason": "Documentation needs one explicit reviewed-gap marker for the demo recovery path.", "missing_items": ["Apply the generic Fix using this structured feedback."]})
        else:
            answer = json.dumps({"completed": True, "reason": "No remaining material gap in demo documentation.", "missing_items": []})
    else:
        answer = json.dumps({"completed": True, "reason": "Target artifact is present and consistent for the demo.", "missing_items": []})
else:
    required = [
        root / "artifacts/project_discovery.md",
        root / "artifacts/project_documentation.md",
        root / "artifacts/e2e_spec.md",
        root / "artifacts/verification_design.md",
        root / "regression/cases.yaml",
        root / "artifacts/qualification.md",
    ]
    missing = [p.relative_to(root).as_posix() for p in required if not p.exists()]
    answer = json.dumps({"passed": not missing, "reason": "all demo deliverables exist" if not missing else "missing deliverables", "missing_items": missing, "checks_run": ["artifact existence"], "suggested_checks": []})

print(json.dumps([
    {"type":"system","subtype":"session_start","session_id":session},
    {"type":"result","subtype":"success","session_id":session,"result":answer},
]))
