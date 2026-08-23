#!/usr/bin/env python3
import argparse, subprocess, sys, tempfile
from pathlib import Path
try:
    from ai_task_runner_validator import ValidatorReport, parse_json
except ModuleNotFoundError:
    import importlib.util as _importlib_util
    from pathlib import Path as _HelperPath

    _helper_path = _HelperPath(__file__).with_name("ai_task_runner_validator.py")
    _spec = _importlib_util.spec_from_file_location("_atr_validator_helper", _helper_path)
    if _spec is None or _spec.loader is None:
        raise
    _helper = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_helper)
    ValidatorReport, parse_json = _helper.ValidatorReport, _helper.parse_json
import yaml

def check(root,payload,expected):
    with tempfile.TemporaryDirectory() as d:
        d=Path(d); src=d/'in.yaml'; out=d/'nested'/'plan.json'; src.write_text(yaml.safe_dump(payload,sort_keys=False),encoding='utf-8')
        r=subprocess.run([sys.executable,str(root/'release_plan.py'),'--input',str(src),'--output',str(out)],cwd=root,text=True,capture_output=True,timeout=20)
        assert r.returncode==0,f'command failed: {r.stdout}{r.stderr}'; assert out.is_file(),'output file missing'
        actual=parse_json(out.read_text(encoding='utf-8'),'plan.json'); assert actual==expected,f'expected={expected}, actual={actual}'

def main():
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file'); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    report=ValidatorReport(root,'example-06-yaml-tool')
    try:
        assert (root/'release_plan.py').is_file(),'missing release_plan.py'
        check(root,{'services':[{'name':'worker','version':'2.0','wave':2},{'name':'api','version':'1.2','wave':1},{'name':'admin','version':'3','wave':1,'enabled':False}]},[{'name':'api','version':'1.2','wave':1},{'name':'worker','version':'2.0','wave':2}])
        check(root,{},[]); check(root,{'services':[{'name':'z','version':'9'},{'name':'a','version':'1'}]},[{'name':'a','version':'1','wave':0},{'name':'z','version':'9','wave':0}])
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'bad.yaml'; out=Path(d)/'o.json'; src.write_text('services:\n  - name: 123\n    version: x\n',encoding='utf-8')
            bad=subprocess.run([sys.executable,str(root/'release_plan.py'),'--input',str(src),'--output',str(out)],cwd=root,text=True,capture_output=True,timeout=20); assert bad.returncode!=0,'invalid item types must fail'
    except Exception as e:
        report.error('E001','Functional validation failed',[str(e)])
    return report.finish()
if __name__=='__main__': raise SystemExit(main())
