#!/usr/bin/env python3
import argparse, subprocess, sys
from pathlib import Path
from ai_task_runner_validator import ValidatorReport, parse_json

def check(root, values):
    r=subprocess.run([sys.executable,str(root/'range_summary.py'),*map(str,values)],cwd=root,text=True,capture_output=True,timeout=20)
    assert r.returncode==0,f'command failed for {values}: {r.stdout}{r.stderr}'
    actual=parse_json(r.stdout, f'range_summary output for {values}')
    expected={'count':len(values),'min':min(values),'max':max(values),'sum':sum(values),'average':sum(values)/len(values)}
    assert actual==expected,f'wrong result for {values}: expected={expected}, actual={actual}'

def main():
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file'); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    report=ValidatorReport(root,'example-02-repair')
    try:
        assert (root/'range_summary.py').is_file(),'missing range_summary.py'
        for values in ([5],[-5,0,10],[-3,-3,6],[2,4,6,8]): check(root,values)
        bad=subprocess.run([sys.executable,str(root/'range_summary.py'),'abc'],cwd=root,text=True,capture_output=True,timeout=20)
        assert bad.returncode!=0,'invalid integer input must fail'
    except Exception as e:
        report.error('E001','Functional validation failed',[str(e)])
    return report.finish()
if __name__=='__main__': raise SystemExit(main())
