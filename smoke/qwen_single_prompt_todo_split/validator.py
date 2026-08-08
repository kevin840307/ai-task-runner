#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from validator_interface import ValidatorReport, run_validation
def validate(root: Path,state_path: Path)->None:
    data=json.loads((root/'input'/'release.json').read_text(encoding='utf-8')); assert state_path.is_file(),'missing runner state'; state=json.loads(state_path.read_text(encoding='utf-8')); tasks=state.get('tasks',[])
    assert len(tasks)>=3,f'expected at least 3 planned tasks, got {len(tasks)}'; assert all(t.get('status')=='completed' for t in tasks),'not all planned tasks are completed'; assert all(t.get('last_review',{}).get('completed') for t in tasks),'every task must be reviewed as completed'
    version=root/'VERSION'; assert version.is_file() and version.read_text(encoding='utf-8').strip()==data['version'],'VERSION mismatch'
    changelog=root/'CHANGELOG.md'; assert changelog.is_file(),'missing CHANGELOG.md'; expected=['# Changelog',f"## {data['version']} - {data['date']}",'### Added',*[f'- {x}' for x in data['added']],'### Fixed',*[f'- {x}' for x in data['fixed']]]; actual=[x for x in changelog.read_text(encoding='utf-8').splitlines() if x.strip()]; assert actual==expected,'unexpected CHANGELOG.md:\n'+'\n'.join(actual)
    summary=root/'release_summary.json'; assert summary.is_file(),'missing release_summary.json'; expected_summary={'name':data['name'],'version':data['version'],'added_count':len(data['added']),'fixed_count':len(data['fixed']),'release_date':data['date']}; assert json.loads(summary.read_text(encoding='utf-8'))==expected_summary,'release_summary.json mismatch'
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve(); return run_validation(ValidatorReport(root,'qwen-single-prompt-todo-split'),lambda:validate(root,Path(a.state_file)))
if __name__=='__main__': raise SystemExit(main())
