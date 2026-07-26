#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


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

    path = Path(args.project_root) / "sorting_algorithms.py"
    if not path.is_file():
        print("missing sorting_algorithms.py")
        return 1

    source = path.read_text(encoding="utf-8")
    if "sorted(" in source or ".sort(" in source:
        print("FAIL: built-in sorting is not allowed")
        return 1

    try:
        module = load_module(path)
        cases = [[], [1], [2, 1], [3, 3, 1, 2, 1], [-3, 0, 2, -1]]
        for name in ("bubble_sort", "insertion_sort"):
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

    print("PASS: runner qwen sorting smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
