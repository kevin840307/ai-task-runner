#!/usr/bin/env python3
import argparse, json, subprocess, sys
from pathlib import Path

def check(root, values):
    r=subprocess.run([sys.executable,str(root/'range_summary.py'),*map(str,values)],cwd=root,text=True,capture_output=True,timeout=20)
    assert r.returncode==0,f'command failed for {values}: {r.stdout}{r.stderr}'
    try: actual=json.loads(r.stdout)
    except json.JSONDecodeError as e: raise AssertionError(f'output is not JSON for {values}: {r.stdout!r}') from e
    expected={'count':len(values),'min':min(values),'max':max(values),'sum':sum(values),'average':sum(values)/len(values)}
    assert actual==expected,f'wrong result for {values}: expected={expected}, actual={actual}'

def main():
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file'); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    try:
        assert (root/'range_summary.py').is_file(),'missing range_summary.py'
        for values in ([5],[-5,0,10],[-3,-3,6],[2,4,6,8]): check(root,values)
        bad=subprocess.run([sys.executable,str(root/'range_summary.py'),'abc'],cwd=root,text=True,capture_output=True,timeout=20)
        assert bad.returncode!=0,'invalid integer input must fail'
        print('VALIDATION_PASSED'); return 0
    except Exception as e:
        print('VALIDATION_FAILED'); print(f'[E001] {e}'); return 1
if __name__=='__main__': raise SystemExit(main())
