#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from common import validate_functions


parser = argparse.ArgumentParser()
parser.add_argument("--project-root", required=True)
parser.add_argument("--state-file", required=True)
args = parser.parse_args()
try:
    validate_functions(
        Path(args.project_root),
        ["bubble_sort", "insertion_sort", "selection_sort"],
    )
except Exception as error:
    print(f"FAIL: {error}")
    raise SystemExit(1)
print("PASS: bubble_sort, insertion_sort, and selection_sort")
