#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from common import validate_functions
from validator_interface import ValidatorReport, run_validation

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a=p.parse_args(); root=Path(a.project_root).resolve()
    return run_validation(ValidatorReport(root,'selection-sort'),lambda:validate_functions(root,['bubble_sort','insertion_sort','selection_sort']))
if __name__=='__main__': raise SystemExit(main())
