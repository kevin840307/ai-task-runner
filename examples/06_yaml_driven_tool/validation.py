#!/usr/bin/env python3
import argparse, json, subprocess, sys, tempfile
from pathlib import Path
import yaml

def check(root,payload,expected):
    with tempfile.TemporaryDirectory() as d:
        d=Path(d); src=d/'in.yaml'; out=d/'nested'/'plan.json'; src.write_text(yaml.safe_dump(payload,sort_keys=False),encoding='utf-8')
        r=subprocess.run([sys.executable,str(root/'release_plan.py'),'--input',str(src),'--output',str(out)],cwd=root,text=True,capture_output=True,timeout=20)
        assert r.returncode==0,f'command failed: {r.stdout}{r.stderr}'; assert out.is_file(),'output file missing'
        actual=json.loads(out.read_text(encoding='utf-8')); assert actual==expected,f'expected={expected}, actual={actual}'

def main():
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file'); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    try:
        assert (root/'release_plan.py').is_file(),'missing release_plan.py'
        check(root,{'services':[{'name':'worker','version':'2.0','wave':2},{'name':'api','version':'1.2','wave':1},{'name':'admin','version':'3','wave':1,'enabled':False}]},[{'name':'api','version':'1.2','wave':1},{'name':'worker','version':'2.0','wave':2}])
        check(root,{},[]); check(root,{'services':[{'name':'z','version':'9'},{'name':'a','version':'1'}]},[{'name':'a','version':'1','wave':0},{'name':'z','version':'9','wave':0}])
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'bad.yaml'; out=Path(d)/'o.json'; src.write_text('services:\n  - name: 123\n    version: x\n',encoding='utf-8')
            bad=subprocess.run([sys.executable,str(root/'release_plan.py'),'--input',str(src),'--output',str(out)],cwd=root,text=True,capture_output=True,timeout=20); assert bad.returncode!=0,'invalid item types must fail'
        print('VALIDATION_PASSED'); return 0
    except Exception as e:
        print('VALIDATION_FAILED'); print(f'[E001] {e}'); return 1
if __name__=='__main__': raise SystemExit(main())
