#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


REQUIRED_FUNCTIONS = ["bubble_sort", "insertion_sort"]


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("sorting_algorithms", path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load sorting_algorithms.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()

    module_path = Path(args.project_root) / "sorting_algorithms.py"
    if not module_path.is_file():
        print("missing sorting_algorithms.py")
        return 1

    source = module_path.read_text(encoding="utf-8")
    if "sorted(" in source or ".sort(" in source:
        print("FAIL: built-in sorting is not allowed")
        return 1

    try:
        module = load_module(module_path)
        cases = [
            [],
            [1],
            [2, 1],
            [3, 3, 1, 2, 1],
            [-5, 0, 4, -1, 4, 2],
            [9, 8, 7, 6, 5],
        ]
        for name in REQUIRED_FUNCTIONS:
            function = getattr(module, name, None)
            if not callable(function):
                raise AssertionError(f"missing callable {name}")
            for values in cases:
                original = list(values)
                result = function(values)
                if values != original:
                    raise AssertionError(f"{name} mutated input")
                if result != sorted(original):
                    raise AssertionError(f"{name} returned {result!r}")
                if result is values:
                    raise AssertionError(f"{name} returned original object")
    except Exception as error:
        print(f"FAIL: {error}")
        return 1

    print("PASS: minimal sorting algorithms behave correctly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
