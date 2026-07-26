#!/usr/bin/env python3
import argparse
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("--project-root",required=True); p.add_argument("--state-file",required=True)
a,_=p.parse_known_args(); root=Path(a.project_root); doc=root/"MIGRATION.md"
if not doc.is_file(): print("Missing MIGRATION.md"); raise SystemExit(1)
text=doc.read_text(encoding="utf-8"); h2=[x for x in text.splitlines() if x.startswith("## ")]
if h2 != ["## Input","## Transformation","## Usage","## Validation"]:
    print(f"Invalid H2 order: {h2}"); raise SystemExit(1)
required=["input/users.csv","input/roles.csv","lowercase","Y","N","sorted","python migrate_users.py","test"]
missing=[x for x in required if x.lower() not in text.lower()]
if missing: print("Missing documentation terms: "+", ".join(missing)); raise SystemExit(1)
if len([x for x in text.splitlines() if x.strip()])>60: print("MIGRATION.md is not concise"); raise SystemExit(1)
print("PASS: migration documentation")
