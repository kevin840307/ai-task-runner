#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, sys, tempfile
from pathlib import Path
from validator_interface import ValidatorReport, run_validation

EXPECTED={
 'order_count':6,'total_amount':'400.00',
 'by_region':{'North':{'order_count':2,'total_amount':'140.00'},'South':{'order_count':2,'total_amount':'180.00'},'West':{'order_count':2,'total_amount':'80.00'}},
 'by_status':{'paid':4,'pending':1,'refunded':1}}


def validate(root: Path) -> None:
    script=root/'summarize_orders.py'; assert script.is_file(), 'Missing summarize_orders.py'
    out=root/'output'/'summary.json'; out.parent.mkdir(exist_ok=True)
    r=subprocess.run([sys.executable,str(script),'--input','input/orders.csv','--output','output/summary.json'],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    assert r.returncode==0, 'summarize_orders.py failed:\n'+r.stdout
    assert out.is_file(), 'Missing output/summary.json'
    raw=out.read_text(encoding='utf-8'); data=json.loads(raw)
    assert raw.endswith('\n'), 'summary.json must end with a newline'
    assert data==EXPECTED, 'Unexpected summary:\n'+raw
    assert list(data)==['order_count','total_amount','by_region','by_status'], 'Top-level key order is wrong'
    with tempfile.TemporaryDirectory() as d:
        bad=Path(d)/'bad.csv'; bad.write_text('order_id,region,status,amount\nX,North,paid,-1\n',encoding='utf-8'); badout=Path(d)/'out.json'
        rr=subprocess.run([sys.executable,str(script),'--input',str(bad),'--output',str(badout)],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
        assert rr.returncode!=0, 'Negative amount was accepted'
        malformed=Path(d)/'malformed.csv'; malformed.write_text('order_id,region,status,amount\nX,North,paid\n',encoding='utf-8'); malformed_out=Path(d)/'malformed.json'
        mr=subprocess.run([sys.executable,str(script),'--input',str(malformed),'--output',str(malformed_out)],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
        assert mr.returncode!=0, 'Malformed row was accepted'


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a,_=p.parse_known_args()
    root=Path(a.project_root).resolve(); return run_validation(ValidatorReport(root,'csv-summary-cli'), lambda: validate(root))
if __name__=='__main__': raise SystemExit(main())
