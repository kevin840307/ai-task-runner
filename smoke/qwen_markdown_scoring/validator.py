#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from validator_interface import ValidatorReport, run_validation

def validate(root: Path, report: ValidatorReport)->None:
    data=json.loads((root/'input'/'sorting_notes.json').read_text(encoding='utf-8')); path=root/'docs'/'sorting_guide.md'; assert path.is_file(),'Missing docs/sorting_guide.md'
    text=path.read_text(encoding='utf-8'); lines=text.splitlines(); h1=[x for x in lines if x.startswith('# ')]; h2=[x for x in lines if x.startswith('## ')]
    assert h1==['# Sorting Guide'],f'invalid H1: {h1}'
    assert h2==['## Overview','## Complexity Table','## Worked Example','## Selection Guide'],f'invalid H2 order: {h2}'
    assert '| Algorithm | Best | Average | Stable |' in text and '|---|---|---|---|' in text,'missing exact complexity table header'
    for item in data['algorithms']:
        row=f"| {item['name']} | {item['best']} | {item['average']} | {item['stable']} |"; assert text.count(row)==1,f'missing or duplicated row: {row}'
    assert '[5, 1, 3, 1]' in text and '[1, 1, 3, 5]' in text,'missing worked example input/output'
    guide=text.split('## Selection Guide',1)[-1]; assert len([x for x in guide.splitlines() if re.match(r'^- ',x)])>=3,'selection guide needs at least three bullets'
    nonempty=len([x for x in lines if x.strip()])
    if nonempty>80: report.warning('W001','Sorting guide may be less concise than intended',[f'non-empty lines: {nonempty}'],fix='Consider shortening the document without removing required content.')

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve(); report=ValidatorReport(root,'qwen-markdown-scoring'); return run_validation(report,lambda:validate(root,report))
if __name__=='__main__': raise SystemExit(main())
