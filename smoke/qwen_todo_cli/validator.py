#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
from validator_interface import ValidatorReport, parse_json, run_validation

def run_cli(root: Path,*args: str):
    return subprocess.run([sys.executable,'todo_cli.py',*args],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)

def command_failure(command,result):
    return f"command failed {command} with exit code {result.returncode}:\n{result.stdout.strip() or '(no stdout/stderr)'}"

def read_state(root: Path, db: Path, label: str):
    listed=run_cli(root,'--db',db.name,'list','--format','json')
    assert listed.returncode==0,command_failure((label,'list --format json'),listed)
    stdout=parse_json(listed.stdout,f'{label}: list --format json stdout')
    stored=parse_json(db.read_text(encoding='utf-8') if db.is_file() else '',f'{label}: {db.name}')
    assert stdout==stored,f'{label}: CLI list and stored JSON differ; stdout={json.dumps(stdout,sort_keys=True)}, stored={json.dumps(stored,sort_keys=True)}'
    return stored

def validate(root: Path)->None:
    script=root/'todo_cli.py'; assert script.is_file(),'missing todo_cli.py'; db=root/'todos.json'; db.unlink(missing_ok=True)
    steps=[
        (('add','Write docs','--priority','high'),[{'id':1,'text':'Write docs','priority':'high','done':False}]),
        (('add','Fix parser','--priority','medium'),[{'id':1,'text':'Write docs','priority':'high','done':False},{'id':2,'text':'Fix parser','priority':'medium','done':False}]),
        (('add','Ship release','--priority','low'),[{'id':1,'text':'Write docs','priority':'high','done':False},{'id':2,'text':'Fix parser','priority':'medium','done':False},{'id':3,'text':'Ship release','priority':'low','done':False}]),
        (('done','2'),[{'id':1,'text':'Write docs','priority':'high','done':False},{'id':2,'text':'Fix parser','priority':'medium','done':True},{'id':3,'text':'Ship release','priority':'low','done':False}]),
        (('delete','3'),[{'id':1,'text':'Write docs','priority':'high','done':False},{'id':2,'text':'Fix parser','priority':'medium','done':True}]),
    ]
    for command,expected in steps:
        full=('--db',db.name,*command); result=run_cli(root,*full); assert result.returncode==0,command_failure(full,result)
        actual=read_state(root,db,'after '+' '.join(command))
        assert actual==expected,'after '+ ' '.join(command)+': expected='+json.dumps(expected,sort_keys=True)+', actual='+json.dumps(actual,sort_keys=True)
    added=run_cli(root,'--db',db.name,'add','Regression check','--priority','low'); assert added.returncode==0,command_failure(('add-after-delete',),added)
    current=read_state(root,db,'after add following delete'); assert current and current[-1].get('id')==4,'IDs must keep increasing after deletion; actual='+json.dumps(current,sort_keys=True)
    exported=run_cli(root,'--db',db.name,'export','--output','summary.md'); assert exported.returncode==0,command_failure(('export',),exported)
    summary=(root/'summary.md').read_text(encoding='utf-8') if (root/'summary.md').is_file() else ''
    for text in ('## Open','Write docs','## Completed','Fix parser'): assert text in summary,'summary.md missing: '+text
    readme=(root/'README.md').read_text(encoding='utf-8') if (root/'README.md').is_file() else ''
    for heading in ('## Usage','## Data format','## Commands','## Examples'): assert heading in readme,f'README.md missing {heading}'

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve(); return run_validation(ValidatorReport(root,'qwen-todo-cli'),lambda:validate(root))
if __name__=='__main__': raise SystemExit(main())
