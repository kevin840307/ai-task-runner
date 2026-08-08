#!/usr/bin/env python3
from __future__ import annotations
import argparse, shutil, subprocess, sys
from pathlib import Path
from validator_interface import ValidatorReport, run_validation


def validate(root: Path) -> None:
    source=root/'input'/'configs'; template=root/'template'/'config.ini.j2'; values=root/'values.yaml'; renderer=root/'render.py'; out=root/'output'/'configs'
    missing=[str(x.relative_to(root)) for x in (template,values,renderer) if not x.is_file()]
    assert not missing, 'Missing required files: '+', '.join(missing)
    value_lines=[line for line in values.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(value_lines)<=24, f'values.yaml has {len(value_lines)} non-empty lines; maximum is 24'
    assert all(len(line)<=160 for line in value_lines), 'values.yaml contains a line longer than 160 characters'
    assert '{{' in template.read_text(encoding='utf-8'), 'template/config.ini.j2 does not contain template placeholders'
    if out.parent.exists(): shutil.rmtree(out.parent)
    result=subprocess.run([sys.executable,str(renderer)],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    assert result.returncode==0, 'render.py failed:\n'+result.stdout
    expected=sorted(p.relative_to(source) for p in source.rglob('*') if p.is_file())
    actual=sorted(p.relative_to(out) for p in out.rglob('*') if p.is_file()) if out.exists() else []
    assert actual==expected, f'Output files differ. expected={expected}, actual={actual}'
    for rel in expected:
        assert (source/rel).read_bytes()==(out/rel).read_bytes(), f'Byte comparison failed: {rel}'


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a,_=p.parse_known_args()
    root=Path(a.project_root).resolve(); return run_validation(ValidatorReport(root,'config-template-roundtrip'), lambda: validate(root))

if __name__=='__main__': raise SystemExit(main())
