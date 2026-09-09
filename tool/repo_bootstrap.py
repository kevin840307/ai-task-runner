"""Repository import bootstrap for directly executed tool scripts."""
from __future__ import annotations
import sys
from pathlib import Path


def ensure_repo_root(file: str) -> Path:
    root = Path(file).resolve().parents[1]
    value = str(root)
    if value not in sys.path:
        sys.path.insert(0, value)
    return root
