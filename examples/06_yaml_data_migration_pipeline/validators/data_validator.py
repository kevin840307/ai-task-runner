#!/usr/bin/env python3
import argparse, json, subprocess, sys, tempfile
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("--project-root",required=True); p.add_argument("--state-file",required=True)
a,_=p.parse_known_args(); root=Path(a.project_root); script=root/"migrate_users.py"
if not script.is_file(): print("Missing migrate_users.py"); raise SystemExit(1)
r=subprocess.run([sys.executable,str(script)],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
if r.returncode: print(r.stdout); raise SystemExit(r.returncode)
out=root/"output"/"users.json"; raw=out.read_text(encoding="utf-8")
expected=[
 {"legacy_id":1001,"full_name":"Alice Chen","email":"alice@example.com","active":True,"roles":["admin","operator"]},
 {"legacy_id":1002,"full_name":"Bob Lin","email":"bob@example.com","active":False,"roles":["viewer"]},
 {"legacy_id":1003,"full_name":"Carol Wu","email":"carol@example.com","active":True,"roles":["operator"]}]
if not raw.endswith("\n") or json.loads(raw)!=expected: print(raw); raise SystemExit(1)
print("PASS: migration output")
