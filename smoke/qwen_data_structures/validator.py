#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("data_structures", path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load data_structures.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()
    path = Path(args.project_root) / "data_structures.py"
    if not path.is_file():
        print("missing data_structures.py")
        return 1
    module = load_module(path)
    try:
        cache = module.LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        if cache.get("a") != 1:
            raise AssertionError("get should return existing value")
        cache.put("c", 3)
        if cache.get("b") != -1:
            raise AssertionError("least recently used key was not evicted")
        if cache.get("c") != 3 or cache.get("a") != 1:
            raise AssertionError("remaining cache values are wrong")
        try:
            module.LRUCache(0)
        except ValueError:
            pass
        else:
            raise AssertionError("capacity 0 should raise ValueError")

        intervals = [[5, 7], [1, 3], [2, 4], [10, 10]]
        original = [item[:] for item in intervals]
        if module.merge_intervals(intervals) != [[1, 4], [5, 7], [10, 10]]:
            raise AssertionError("merge_intervals result is wrong")
        if intervals != original:
            raise AssertionError("merge_intervals mutated input")

        if module.top_k_frequent([4, 1, 4, 2, 2, 2, 3, 3], 3) != [2, 3, 4]:
            raise AssertionError("top_k_frequent ordering is wrong")
        if module.top_k_frequent([5, 5, 6], 10) != [5, 6]:
            raise AssertionError("top_k_frequent should cap at unique values")
    except Exception as error:
        print(f"FAIL: {error}")
        return 1
    print("PASS: data structures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
