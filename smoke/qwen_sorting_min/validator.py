#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, importlib.util, sys
from pathlib import Path
from validator_interface import ValidatorReport, run_validation
REQUIRED_FUNCTIONS=['bubble_sort','insertion_sort']
def load_module(path: Path):
    spec=importlib.util.spec_from_file_location('sorting_algorithms',path); assert spec and spec.loader,'could not load sorting_algorithms.py'; module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module); return module
def assert_no_builtin_sorting(source: str)->None:
    tree=ast.parse(source)
    imports={name.split('.',1)[0] for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom)) for name in ([a.name for a in node.names] if isinstance(node,ast.Import) else ([node.module] if node.module else []))}
    third_party=sorted(name for name in imports if name not in sys.stdlib_module_names); assert not third_party,'standard-library only: '+', '.join(third_party)
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and ((isinstance(node.func,ast.Name) and node.func.id=='sorted') or (isinstance(node.func,ast.Attribute) and node.func.attr=='sort')): raise AssertionError('built-in sorting is not allowed')
def validate(root: Path)->None:
    path=root/'sorting_algorithms.py'; assert path.is_file(),'missing sorting_algorithms.py'; assert_no_builtin_sorting(path.read_text(encoding='utf-8')); module=load_module(path); cases=[[],[1],[2,1],[3,3,1,2,1],[-5,0,4,-1,4,2],[9,8,7,6,5]]
    for name in REQUIRED_FUNCTIONS:
        fn=getattr(module,name,None); assert callable(fn),f'missing callable {name}'
        for values in cases:
            original=list(values); result=fn(values); assert values==original,f'{name} mutated input'; assert result==sorted(original),f'{name} returned {result!r}'; assert result is not values,f'{name} returned original object'
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve(); return run_validation(ValidatorReport(root,'qwen-sorting-min'),lambda:validate(root))
if __name__=='__main__': raise SystemExit(main())
