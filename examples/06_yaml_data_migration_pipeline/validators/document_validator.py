#!/usr/bin/env python3
import argparse
from pathlib import Path
from validator_interface import ValidatorReport, run_validation

def validate(root: Path)->None:
    doc=root/'MIGRATION.md'; assert doc.is_file(), 'Missing MIGRATION.md'
    text=doc.read_text(encoding='utf-8'); h2=[x for x in text.splitlines() if x.startswith('## ')]
    assert h2==['## Input','## Transformation','## Usage','## Validation'], f'Invalid H2 order: {h2}'
    required=['input/users.csv','input/roles.csv','lowercase','Y','N','sorted','python migrate_users.py','test']
    missing=[x for x in required if x.lower() not in text.lower()]; assert not missing, 'Missing documentation terms: '+', '.join(missing)
    assert len([x for x in text.splitlines() if x.strip()])<=60, 'MIGRATION.md is not concise'

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    return run_validation(ValidatorReport(root,'migration-documentation'), lambda: validate(root))
if __name__=='__main__': raise SystemExit(main())
