#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, importlib.util, sys
from pathlib import Path
from validator_interface import ValidatorReport, run_validation

def load_module(path: Path):
    spec=importlib.util.spec_from_file_location('data_structures',path); assert spec and spec.loader, 'could not load data_structures.py'
    module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module); return module

def validate(root: Path)->None:
    path=root/'data_structures.py'; assert path.is_file(), 'missing data_structures.py'; source=path.read_text(encoding='utf-8'); tree=ast.parse(source); imports={name.split('.',1)[0] for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom)) for name in ([a.name for a in node.names] if isinstance(node,ast.Import) else ([node.module] if node.module else []))}; third_party=sorted(name for name in imports if name not in sys.stdlib_module_names); assert not third_party,'data_structures.py must use only the Python standard library: '+', '.join(third_party); module=load_module(path)
    cache=module.LRUCache(2); cache.put('a',1); cache.put('b',2); assert cache.get('a')==1, 'get should return existing value'; cache.put('c',3); assert cache.get('b')==-1, 'get must update recency'; assert cache.get('c')==3 and cache.get('a')==1, 'remaining cache values are wrong'
    cache=module.LRUCache(2); cache.put('a',1); cache.put('b',2); cache.put('a',10); cache.put('c',3); assert cache.get('b')==-1 and cache.get('a')==10, 'put on an existing key must update recency and value'
    try: module.LRUCache(0)
    except ValueError: pass
    else: raise AssertionError('capacity 0 should raise ValueError')
    intervals=[[5,7],[1,3],[2,4],[10,10]]; original=[x[:] for x in intervals]; assert module.merge_intervals(intervals)==[[1,4],[5,7],[10,10]], 'merge_intervals result is wrong'; assert intervals==original, 'merge_intervals mutated input'
    assert module.top_k_frequent([4,1,4,2,2,2,3,3],3)==[2,3,4], 'top_k_frequent ordering is wrong'; assert module.top_k_frequent([5,5,6],10)==[5,6], 'top_k_frequent should cap at unique values'

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve()
    return run_validation(ValidatorReport(root,'qwen-data-structures'), lambda: validate(root))
if __name__=='__main__': raise SystemExit(main())
