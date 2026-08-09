#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
from validator_interface import ValidatorReport, run_validation
def run_cli(root: Path,*args: str): return subprocess.run([sys.executable,'todo_cli.py',*args],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
def command_failure(command,result): return f"command failed {command} with exit code {result.returncode}:\n{result.stdout.strip() or '(no stdout/stderr)'}"
def validate(root: Path)->None:
    script=root/'todo_cli.py'; assert script.is_file(),'missing todo_cli.py'; db=root/'todos.json'; db.unlink(missing_ok=True)
    commands=[('--db','todos.json','add','Write docs','--priority','high'),('--db','todos.json','add','Fix parser','--priority','medium'),('--db','todos.json','add','Ship release','--priority','low'),('--db','todos.json','done','2'),('--db','todos.json','delete','3')]
    for command in commands:
        r=run_cli(root,*command); assert r.returncode==0,command_failure(command,r)
    listed=run_cli(root,'--db','todos.json','list','--format','json'); assert listed.returncode==0,command_failure(('list',),listed)
    expected=[{'id':1,'text':'Write docs','priority':'high','done':False},{'id':2,'text':'Fix parser','priority':'medium','done':True}]
    todos=json.loads(listed.stdout); assert todos==expected,'unexpected list output:\n'+json.dumps(todos,indent=2,sort_keys=True); assert json.loads(db.read_text(encoding='utf-8'))==expected,'unexpected stored JSON'
    added=run_cli(root,'--db','todos.json','add','Regression check','--priority','low'); assert added.returncode==0,command_failure(('add-after-delete',),added)
    current=json.loads(run_cli(root,'--db','todos.json','list','--format','json').stdout); assert current[-1].get('id')==4,'IDs must keep increasing after deletion'
    exported=run_cli(root,'--db','todos.json','export','--output','summary.md'); assert exported.returncode==0,command_failure(('export',),exported)
    summary=(root/'summary.md').read_text(encoding='utf-8') if (root/'summary.md').is_file() else ''
    for text in ('## Open','Write docs','## Completed','Fix parser'): assert text in summary,'summary.md missing: '+text
    readme=(root/'README.md').read_text(encoding='utf-8') if (root/'README.md').is_file() else ''
    for heading in ('## Usage','## Data format','## Commands','## Examples'): assert heading in readme,f'README.md missing {heading}'
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve(); return run_validation(ValidatorReport(root,'qwen-todo-cli'),lambda:validate(root))
if __name__=='__main__': raise SystemExit(main())
