#!/usr/bin/env python3
import argparse, json, subprocess, sys, tempfile
from pathlib import Path

def call(root, db, *args):
    return subprocess.run([sys.executable,str(root/'todo_cli.py'),'--db',str(db),*args],cwd=root,text=True,capture_output=True,timeout=20)
def load(root,db):
    r=call(root,db,'list','--format','json'); assert r.returncode==0,f'list failed: {r.stdout}{r.stderr}'
    try:return json.loads(r.stdout)
    except json.JSONDecodeError as e: raise AssertionError(f'list returned invalid JSON: {r.stdout!r}') from e

def main():
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file'); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    try:
        assert (root/'todo_cli.py').is_file(),'missing todo_cli.py'
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'todos.json'; assert load(root,db)==[],'missing DB should behave as empty list'
            for text,priority in [('Write docs','high'),('Fix parser','medium'),('Ship release','low')]:
                r=call(root,db,'add',text,'--priority',priority); assert r.returncode==0,f'add failed: {r.stdout}{r.stderr}'
            items=load(root,db); assert [x['id'] for x in items]==[1,2,3],f'IDs wrong: {items}'
            assert [(x['text'],x['priority'],x['done']) for x in items]==[('Write docs','high',False),('Fix parser','medium',False),('Ship release','low',False)],f'added values wrong: {items}'
            assert call(root,db,'done','2').returncode==0,'done 2 failed'; items=load(root,db); assert [x['done'] for x in items]==[False,True,False],f'done changed wrong rows: {items}'
            assert call(root,db,'delete','1').returncode==0,'delete 1 failed'; assert [x['id'] for x in load(root,db)]==[2,3],'delete removed wrong item'
            assert call(root,db,'add','Next','--priority','low').returncode==0,'add after delete failed'; assert [x['id'] for x in load(root,db)]==[2,3,4],'ID progression is not stable'
            assert call(root,db,'done','999').returncode!=0,'unknown ID must fail'; assert call(root,db,'add','Bad','--priority','urgent').returncode!=0,'invalid priority must fail'
        print('VALIDATION_PASSED'); return 0
    except Exception as e:
        print('VALIDATION_FAILED'); print(f'[E001] {e}'); return 1
if __name__=='__main__': raise SystemExit(main())
