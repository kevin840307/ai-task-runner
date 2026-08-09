#!/usr/bin/env python3
import argparse, ast, json, subprocess, sys
from pathlib import Path
from validator_interface import ValidatorReport, run_validation

EXPECTED=[
 {'legacy_id':1001,'full_name':'Alice Chen','email':'alice@example.com','active':True,'roles':['admin','operator']},
 {'legacy_id':1002,'full_name':'Bob Lin','email':'bob@example.com','active':False,'roles':['viewer']},
 {'legacy_id':1003,'full_name':'Carol Wu','email':'carol@example.com','active':True,'roles':['operator']}]

def validate(root: Path)->None:
    script=root/'migrate_users.py'; assert script.is_file(), 'Missing migrate_users.py'
    tree=ast.parse(script.read_text(encoding='utf-8')); imports={name.split('.',1)[0] for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom)) for name in ([a.name for a in node.names] if isinstance(node,ast.Import) else ([node.module] if node.module else []))}; third_party=sorted(name for name in imports if name not in sys.stdlib_module_names); assert not third_party,'migrate_users.py must use only the Python standard library: '+', '.join(third_party)
    r=subprocess.run([sys.executable,str(script)],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    assert r.returncode==0, 'migrate_users.py failed:\n'+r.stdout
    out=root/'output'/'users.json'; assert out.is_file(), 'Missing output/users.json'
    raw=out.read_text(encoding='utf-8'); expected_raw=json.dumps(EXPECTED,ensure_ascii=False,indent=2)+'\n'; assert raw==expected_raw, 'users.json must use the required values, order, indent=2, and final newline:\n'+raw

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    return run_validation(ValidatorReport(root,'migration-data'), lambda: validate(root))
if __name__=='__main__': raise SystemExit(main())
