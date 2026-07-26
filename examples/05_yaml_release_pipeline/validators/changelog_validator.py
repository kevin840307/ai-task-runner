#!/usr/bin/env python3
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("--project-root",required=True); p.add_argument("--state-file",required=True)
a,_=p.parse_known_args(); root=Path(a.project_root); out=root/"CHANGELOG.md"
if not out.is_file(): print("Missing CHANGELOG.md"); raise SystemExit(1)
data=json.loads((root/"release_notes.json").read_text(encoding="utf-8")); lines=out.read_text(encoding="utf-8").splitlines()
expected=["# Changelog",f"## {data['version']} - {data['date']}","### Added",*[f"- {x}" for x in data['added']],"### Fixed",*[f"- {x}" for x in data['fixed']]]
actual=[x for x in lines if x.strip()]
if actual!=expected: print("Unexpected CHANGELOG.md:\n"+"\n".join(actual)); raise SystemExit(1)
print("PASS: changelog format")
