#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, importlib.util, json, subprocess, sys, traceback
from pathlib import Path
from validator_interface import ValidatorReport, run_validation
EXPECTED_BATCH=[{'expression':'1 + 2 * 3','result':7.0},{'expression':'(10 - 4) / 3','result':2.0},{'expression':'-2.5 * (4 + 1)','result':-12.5},{'expression':'8 / (2 + 2)','result':2.0},{'expression':'bad + 1','error':'invalid'}]
def close_enough(actual,expected): return abs(float(actual)-expected)<1e-9
def load_module(script: Path):
    spec=importlib.util.spec_from_file_location('expression_eval_case',script); assert spec and spec.loader,'cannot import expression_eval.py'; module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
def uses_forbidden_dynamic_execution(source: str)->bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,ast.Call) and ((isinstance(node.func,ast.Name) and node.func.id in {'eval','exec'}) or (isinstance(node.func,ast.Attribute) and node.func.attr in {'eval','exec'})): return True
    return False
def validate(root: Path)->None:
    script=root/'expression_eval.py'; assert script.is_file(),'missing expression_eval.py'; source=script.read_text(encoding='utf-8'); assert not uses_forbidden_dynamic_execution(source),'expression_eval.py must not call eval or exec'; module=load_module(script)
    for expression,expected in {'1 + 2 * 3':7.0,'(10 - 4) / 3':2.0,'-2.5 * (4 + 1)':-12.5,'3.5 + .5':4.0,'--4':4.0}.items():
        try: actual=module.evaluate(expression)
        except Exception as error: raise AssertionError(f"evaluate({expression!r}) raised {error}:\n"+traceback.format_exc(limit=6)) from error
        assert close_enough(actual,expected),f'evaluate({expression!r}) returned {actual!r}, expected {expected!r}'
    cli=subprocess.run([sys.executable,str(script),'1 + 2 * 3'],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30); assert cli.returncode==0 and cli.stdout.strip() in {'7','7.0'},'single-expression CLI failed:\n'+cli.stdout
    batch=subprocess.run([sys.executable,str(script),'--batch','input/expressions.txt','--json','results.json','--markdown','results.md'],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30); assert batch.returncode==0,'batch CLI failed:\n'+batch.stdout
    path=root/'results.json'; assert path.is_file(),'missing results.json'; results=json.loads(path.read_text(encoding='utf-8')); assert len(results)==len(EXPECTED_BATCH),f'expected {len(EXPECTED_BATCH)} batch rows, got {len(results)}'
    for actual,expected in zip(results,EXPECTED_BATCH):
        assert actual.get('expression')==expected['expression'],'batch expression order mismatch'
        if 'result' in expected: assert 'result' in actual and close_enough(actual['result'],expected['result']),'batch result mismatch:\n'+json.dumps(results,indent=2)
        else: assert 'error' in actual,'invalid expression did not produce an error entry'
    markdown=(root/'results.md').read_text(encoding='utf-8') if (root/'results.md').is_file() else ''; assert all(x in markdown for x in ('# Expression Results','| Expression | Result |','bad + 1')),'results.md missing required content'
    readme=(root/'README.md').read_text(encoding='utf-8') if (root/'README.md').is_file() else ''
    for heading in ('## Usage','## Supported syntax','## Error handling','## Examples'): assert heading in readme,f'README.md missing {heading}'
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve(); return run_validation(ValidatorReport(root,'qwen-expression-evaluator'),lambda:validate(root))
if __name__=='__main__': raise SystemExit(main())
