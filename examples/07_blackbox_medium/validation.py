#!/usr/bin/env python3
# Deliberately black-box: this validator never reads or inspects implementation source.
import argparse, csv, json, subprocess, sys, tempfile
from pathlib import Path
from ai_task_runner_validator import ValidatorReport, parse_json
import yaml

def run_case(root, build, expected_records, expected_summary):
    with tempfile.TemporaryDirectory() as d:
        base=Path(d); inp=base/'input'; out=base/'output'; inp.mkdir(); build(inp)
        r=subprocess.run([sys.executable,str(root/'inventory_cli.py'),'scan','--input',str(inp),'--output',str(out)],cwd=root,text=True,capture_output=True,timeout=30)
        assert r.returncode==0,f'scan failed: stdout={r.stdout!r} stderr={r.stderr!r}'
        assert (out/'records.json').is_file(),'records.json missing'; assert (out/'summary.json').is_file(),'summary.json missing'
        records=parse_json((out/'records.json').read_text(encoding='utf-8'),'records.json'); summary=parse_json((out/'summary.json').read_text(encoding='utf-8'),'summary.json')
        assert records==expected_records,f'records mismatch: expected={expected_records}, actual={records}'
        assert summary==expected_summary,f'summary mismatch: expected={expected_summary}, actual={summary}'

def case_main(inp):
    (inp/'nested').mkdir(); (inp/'a.json').write_text(json.dumps([{'id':1,'name':'A'},{'id':2,'name':'B'}]),encoding='utf-8')
    (inp/'nested'/'b.yaml').write_text(yaml.safe_dump({'records':[{'id':3,'name':'三'}]},allow_unicode=True),encoding='utf-8')
    with (inp/'nested'/'c.csv').open('w',encoding='utf-8',newline='') as f: w=csv.DictWriter(f,fieldnames=['id','name']); w.writeheader(); w.writerow({'id':'4','name':'C'})
    (inp/'ignore.txt').write_text('ignored',encoding='utf-8'); (inp/'bad.JSON').write_text('{bad',encoding='utf-8')

def case_alt(inp):
    (inp/'UPPER.CSV').write_text('key,value\nx,1\ny,2\n',encoding='utf-8'); (inp/'single.yml').write_text('- enabled: true\n',encoding='utf-8')

def main():
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file'); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    report=ValidatorReport(root,'example-07-blackbox')
    try:
        assert (root/'inventory_cli.py').is_file(),'missing inventory_cli.py'
        run_case(root,case_main,[{'id':1,'name':'A','_source':'a.json','_index':0},{'id':2,'name':'B','_source':'a.json','_index':1},{'id':3,'name':'三','_source':'nested/b.yaml','_index':0},{'id':'4','name':'C','_source':'nested/c.csv','_index':0}],{'files':3,'records':4,'by_format':{'json':1,'yaml':1,'csv':1},'errors':['bad.JSON']})
        # Order is _source then _index, so UPPER.CSV sorts before single.yml.
        run_case(root,case_alt,[{'key':'x','value':'1','_source':'UPPER.CSV','_index':0},{'key':'y','value':'2','_source':'UPPER.CSV','_index':1},{'enabled':True,'_source':'single.yml','_index':0}],{'files':2,'records':3,'by_format':{'csv':1,'yaml':1},'errors':[]})
        run_case(root,lambda inp: None,[],{'files':0,'records':0,'by_format':{},'errors':[]})
    except Exception as e:
        report.error('E001','Functional validation failed',[str(e)])
    return report.finish()
if __name__=='__main__': raise SystemExit(main())
