#!/usr/bin/env python3
import argparse, json, subprocess, sys
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("--project-root",required=True); p.add_argument("--state-file",required=True)
a,_=p.parse_known_args(); root=Path(a.project_root)
version=json.loads((root/"release_notes.json").read_text(encoding="utf-8"))["version"]
if not (root/"VERSION").is_file() or (root/"VERSION").read_text(encoding="utf-8").strip()!=version:
    print("VERSION mismatch"); raise SystemExit(1)
r=subprocess.run([sys.executable,"app.py","--version"],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
if r.returncode or r.stdout.strip()!=version: print(r.stdout); raise SystemExit(1)
r=subprocess.run([sys.executable,"app.py"],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
if r.returncode: print(r.stdout); raise SystemExit(1)
print("PASS: version behavior")
