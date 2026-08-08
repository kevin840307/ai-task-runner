#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, importlib.util, random, sys
from pathlib import Path
from validator_interface import ValidatorReport, run_validation
REQUIRED_FUNCTIONS=['bubble_sort','insertion_sort','merge_sort','quick_sort']
def load_module(path: Path):
    spec=importlib.util.spec_from_file_location('sorting_algorithms',path); assert spec and spec.loader,'could not load sorting_algorithms.py'; module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module); return module
def assert_no_builtin_sorting(source: str)->None:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,ast.Call) and ((isinstance(node.func,ast.Name) and node.func.id=='sorted') or (isinstance(node.func,ast.Attribute) and node.func.attr=='sort')): raise AssertionError('built-in sorting is not allowed')
def cases():
    fixed=[[],[1],[2,1],[3,3,1,2,1],[-5,0,4,-1,4,2],[9,8,7,6,5,4,3,2,1]]; rng=random.Random(12345); return fixed+[[rng.randint(-20,20) for _ in range(size)] for size in range(2,20)]
def validate(root: Path)->None:
    path=root/'sorting_algorithms.py'; assert path.is_file(),'missing sorting_algorithms.py'; assert_no_builtin_sorting(path.read_text(encoding='utf-8')); module=load_module(path)
    for name in REQUIRED_FUNCTIONS:
        fn=getattr(module,name,None); assert callable(fn),f'missing callable {name}'
        for values in cases():
            original=list(values); result=fn(values); assert values==original,f'{name} mutated its input'; assert result==sorted(original),f'{name} returned {result!r}, expected {sorted(original)!r}'; assert result is not values,f'{name} returned the input list object'
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve(); return run_validation(ValidatorReport(root,'qwen-sorting'),lambda:validate(root))
if __name__=='__main__': raise SystemExit(main())
