#!/usr/bin/env python3
import argparse, json
from pathlib import Path
from validator_interface import ValidatorReport, run_validation

def validate(root: Path)->None:
    out=root/'CHANGELOG.md'; assert out.is_file(), 'Missing CHANGELOG.md'
    data=json.loads((root/'release_notes.json').read_text(encoding='utf-8'))
    expected=['# Changelog',f"## {data['version']} - {data['date']}",'### Added',*[f'- {x}' for x in data['added']],'### Fixed',*[f'- {x}' for x in data['fixed']]]
    actual=[x for x in out.read_text(encoding='utf-8').splitlines() if x.strip()]
    assert actual==expected, 'Unexpected CHANGELOG.md:\n'+'\n'.join(actual)

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    return run_validation(ValidatorReport(root,'release-changelog'), lambda: validate(root))
if __name__=='__main__': raise SystemExit(main())
