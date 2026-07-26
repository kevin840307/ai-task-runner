from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


CASES = [
    [],
    [1],
    [2, 1],
    [3, 3, 1, 2, 1],
    [-3, 0, 2, -1],
    [9, 7, 5, 3, 1],
]


def load_module(root: Path):
    path = root / "sorting_algorithms.py"
    if not path.is_file():
        raise AssertionError("missing sorting_algorithms.py")
    source = path.read_text(encoding="utf-8")
    if "sorted(" in source or ".sort(" in source:
        raise AssertionError("built-in sorting is not allowed")
    spec = importlib.util.spec_from_file_location("sorting_algorithms", path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load sorting_algorithms.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_functions(root: Path, names: list[str]) -> None:
    module = load_module(root)
    for name in names:
        function = getattr(module, name, None)
        if not callable(function):
            raise AssertionError(f"missing callable {name}")
        for values in CASES:
            original = list(values)
            result = function(values)
            if values != original:
                raise AssertionError(f"{name} mutated input")
            if result is values:
                raise AssertionError(f"{name} returned original list")
            if result != sorted(original):
                raise AssertionError(f"{name} returned {result!r} for {original!r}")
