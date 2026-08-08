#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from validator_interface import ValidatorReport, run_validation
EXPECTED='Qwen smoke test completed.\n'
def validate(root: Path)->None:
    target=root/'hello.txt'; assert target.is_file(), 'missing hello.txt'; assert target.read_text(encoding='utf-8')==EXPECTED, 'unexpected hello.txt content'
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve()
    return run_validation(ValidatorReport(root,'qwen-simple'), lambda: validate(root))
if __name__=='__main__': raise SystemExit(main())
