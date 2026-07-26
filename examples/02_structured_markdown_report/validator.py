#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

p=argparse.ArgumentParser(); p.add_argument("--project-root",required=True); p.add_argument("--state-file",required=True)
a,_=p.parse_known_args(); root=Path(a.project_root)
src=root/"input"/"incidents.json"; out=root/"output"/"incident_report.md"
if not out.is_file(): print("Missing output/incident_report.md"); raise SystemExit(1)
data=json.loads(src.read_text(encoding="utf-8")); text=out.read_text(encoding="utf-8")
lines=text.splitlines()
if not lines or lines[0] != "# Incident Report": print("Invalid H1"); raise SystemExit(1)
h2=[line for line in lines if line.startswith("## ")]
if h2 != ["## Summary","## Incidents","## Follow-up Actions"]:
    print(f"Invalid H2 order: {h2}"); raise SystemExit(1)
services=", ".join(sorted({x["service"] for x in data}))
summary=[f"- Total: {len(data)}",f"- High severity: {sum(x['severity']=='high' for x in data)}",f"- Services: {services}"]
summary_start=lines.index("## Summary")+1
actual_summary=[x for x in lines[summary_start:lines.index("## Incidents")] if x.strip()]
if actual_summary != summary: print(f"Invalid summary: {actual_summary}"); raise SystemExit(1)
heads=[line for line in lines if line.startswith("### ")]
expected_heads=[f"### {x['id']} — {x['title']}" for x in data]
if heads != expected_heads: print(f"Invalid incident headings: {heads}"); raise SystemExit(1)
for item in data:
    section=f"### {item['id']} — {item['title']}"
    pos=lines.index(section)
    required=["| Field | Value |","|---|---|",f"| Severity | {item['severity']} |",f"| Service | {item['service']} |",f"| Owner | {item['owner']} |"]
    actual=[x for x in lines[pos+1:pos+8] if x.strip()][:5]
    if actual != required: print(f"Invalid table for {item['id']}: {actual}"); raise SystemExit(1)
actions=[f"- [ ] {x['id']}: {x['action']} (@{x['owner']})" for x in data]
action_pos=lines.index("## Follow-up Actions")+1
actual_actions=[x for x in lines[action_pos:] if x.strip()]
if actual_actions != actions: print(f"Invalid actions: {actual_actions}"); raise SystemExit(1)
print("PASS: structured incident report")
