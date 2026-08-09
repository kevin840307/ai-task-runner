#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
from validator_interface import ValidatorReport, run_validation
EXPECTED_REPORT={'total_revenue':333.19,'order_count':6,'units_by_product':{'Doodad':5,'Gadget':6,'Widget':6},'revenue_by_region':{'East':76.23,'North':79.96,'South':59.0,'West':118.0},'top_product_by_revenue':{'product':'Gadget','revenue':177.0},'date_range':{'start':'2026-07-01','end':'2026-07-03'}}
def validate(root: Path)->None:
    script=root/'analyze_sales.py'; assert script.is_file(),'missing analyze_sales.py'
    result=subprocess.run([sys.executable,str(script),'--input','input/sales.csv','--json','report.json','--markdown','report.md'],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    assert result.returncode==0,'analyze_sales.py failed:\n'+result.stdout
    report_path=root/'report.json'; assert report_path.is_file(),'missing report.json'; actual=json.loads(report_path.read_text(encoding='utf-8')); assert actual==EXPECTED_REPORT,'unexpected report.json:\n'+json.dumps(actual,indent=2,sort_keys=True)
    markdown=(root/'report.md').read_text(encoding='utf-8') if (root/'report.md').is_file() else ''; lines=markdown.splitlines(); assert any(x.startswith('# ') for x in lines),'report.md needs a title'; missing=[x for x in ['333.19','East','North','South','West','Gadget'] if x not in markdown]; assert not missing,'report.md missing report content: '+', '.join(missing)
    readme=(root/'README.md').read_text(encoding='utf-8') if (root/'README.md').is_file() else ''
    for heading in ('## Usage','## Outputs','## Assumptions'): assert heading in readme,f'README.md missing {heading}'
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve(); return run_validation(ValidatorReport(root,'qwen-csv-analyzer'),lambda:validate(root))
if __name__=='__main__': raise SystemExit(main())
