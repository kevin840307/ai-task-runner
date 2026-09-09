#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, importlib.util, sys
from pathlib import Path
from validator_interface import ValidatorReport, run_validation

def load_module(path: Path):
    spec=importlib.util.spec_from_file_location('sorting_algorithms',path); assert spec and spec.loader, 'could not load sorting_algorithms.py'
    module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module); return module

def assert_no_builtin_sorting(source: str)->None:
    tree=ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and ((isinstance(node.func,ast.Name) and node.func.id=='sorted') or (isinstance(node.func,ast.Attribute) and node.func.attr=='sort')):
            raise AssertionError('built-in sorting is not allowed')

def validate(root: Path)->None:
    path=root/'sorting_algorithms.py'; assert path.is_file(), 'missing sorting_algorithms.py'; assert_no_builtin_sorting(path.read_text(encoding='utf-8')); module=load_module(path)
    cases=[[],[1],[2,1],[3,3,1,2,1],[-3,0,2,-1]]
    for name in ('bubble_sort','insertion_sort'):
        fn=getattr(module,name,None); assert callable(fn), f'missing callable {name}'
        for values in cases:
            original=list(values); result=fn(values); assert values==original, f'{name} mutated input'; assert result==sorted(original), f'{name} returned {result!r}'; assert result is not values, f'{name} returned original object'

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve()
    return run_validation(ValidatorReport(root,'qwen-runner-sorting'), lambda: validate(root))
if __name__=='__main__': raise SystemExit(main())
