#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("--project-root",required=True); p.add_argument("--state-file",required=True)
a,_=p.parse_known_args(); root=Path(a.project_root); script=root/"summarize_orders.py"
if not script.is_file(): print("Missing summarize_orders.py"); raise SystemExit(1)
out=root/"output"/"summary.json"; out.parent.mkdir(exist_ok=True)
r=subprocess.run([sys.executable,str(script),"--input","input/orders.csv","--output","output/summary.json"],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
if r.returncode: print(r.stdout); raise SystemExit(r.returncode)
expected={
 "order_count":6,
 "total_amount":"400.00",
 "by_region":{
   "North":{"order_count":2,"total_amount":"140.00"},
   "South":{"order_count":2,"total_amount":"180.00"},
   "West":{"order_count":2,"total_amount":"80.00"}},
 "by_status":{"paid":4,"pending":1,"refunded":1}}
raw=out.read_text(encoding="utf-8")
if not raw.endswith("\n") or json.loads(raw)!=expected:
    print(f"Unexpected summary:\n{raw}"); raise SystemExit(1)
if list(json.loads(raw)) != ["order_count","total_amount","by_region","by_status"]:
    print("Top-level key order is wrong"); raise SystemExit(1)
with tempfile.TemporaryDirectory() as d:
    bad=Path(d)/"bad.csv"; bad.write_text("order_id,region,status,amount\nX,North,paid,-1\n",encoding="utf-8")
    badout=Path(d)/"out.json"
    rr=subprocess.run([sys.executable,str(script),"--input",str(bad),"--output",str(badout)],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    if rr.returncode==0: print("Negative amount was accepted"); raise SystemExit(1)
print("PASS: CSV summary CLI")
