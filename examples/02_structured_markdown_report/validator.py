#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from validator_interface import ValidatorReport, run_validation


def validate(root: Path) -> None:
    src=root/'input'/'incidents.json'; out=root/'output'/'incident_report.md'
    assert out.is_file(), 'Missing output/incident_report.md'
    data=json.loads(src.read_text(encoding='utf-8')); text=out.read_text(encoding='utf-8'); lines=text.splitlines()
    assert lines and lines[0]=='# Incident Report', 'Invalid H1'
    h2=[line for line in lines if line.startswith('## ')]
    assert h2==['## Summary','## Incidents','## Follow-up Actions'], f'Invalid H2 order: {h2}'
    services=', '.join(sorted({x['service'] for x in data}))
    summary=[f'- Total: {len(data)}',f"- High severity: {sum(x['severity']=='high' for x in data)}",f'- Services: {services}']
    actual=[x for x in lines[lines.index('## Summary')+1:lines.index('## Incidents')] if x.strip()]
    assert actual==summary, f'Invalid summary: {actual}'
    heads=[line for line in lines if line.startswith('### ')]; expected=[f"### {x['id']} — {x['title']}" for x in data]
    assert heads==expected, f'Invalid incident headings: {heads}'
    for item in data:
        pos=lines.index(f"### {item['id']} — {item['title']}")
        block=[x for x in lines[pos+1:pos+10] if x.strip()]
        required=[f"| Severity | {item['severity']} |",f"| Service | {item['service']} |",f"| Owner | {item['owner']} |"]
        assert all(row in block for row in required), f"Invalid table for {item['id']}"
    actions=[f"- [ ] {x['id']}: {x['action']} (@{x['owner']})" for x in data]
    assert [x for x in lines[lines.index('## Follow-up Actions')+1:] if x.strip()]==actions, 'Invalid follow-up actions'


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a,_=p.parse_known_args()
    root=Path(a.project_root).resolve(); return run_validation(ValidatorReport(root,'structured-markdown-report'), lambda: validate(root))
if __name__=='__main__': raise SystemExit(main())
