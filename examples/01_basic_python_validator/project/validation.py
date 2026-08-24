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

def run(root, text):
    with tempfile.TemporaryDirectory() as d:
        d=Path(d); src=d/'in.txt'; out=d/'nested'/'stats.json'; src.write_text(text,encoding='utf-8')
        r=subprocess.run([sys.executable,str(root/'text_stats.py'),'--input',str(src),'--output',str(out)],cwd=root,text=True,capture_output=True,timeout=20)
        assert r.returncode==0, f'command failed: {r.stdout}{r.stderr}'
        assert out.is_file(), 'output JSON was not created'
        return parse_json(out.read_text(encoding='utf-8'), 'stats.json')

def main():
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file'); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    report=ValidatorReport(root,'example-01-basic')
    try:
        script=root/'text_stats.py'; assert script.is_file(),'missing text_stats.py'
        for text in ['alpha beta\n\ngamma\n','你好 world\nsecond line','']:
            lines=text.splitlines(); expected={'lines':len(lines),'words':len(text.split()),'characters':len(text),'non_empty_lines':sum(bool(x.strip()) for x in lines)}
            actual=run(root,text); assert actual==expected,f'wrong stats for {text!r}: expected={expected}, actual={actual}'
        missing=subprocess.run([sys.executable,str(script),'--input',str(root/'does-not-exist.txt'),'--output',str(root/'unused.json')],cwd=root,text=True,capture_output=True,timeout=20)
        assert missing.returncode!=0,'missing input must return non-zero'
    except Exception as e:
        report.error('E001','Functional validation failed',[str(e)])
    return report.finish()
if __name__=='__main__': raise SystemExit(main())
