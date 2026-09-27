#!/usr/bin/env python3
"""Print the data-only top-level execution mode catalog as JSON."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.execution_modes import execution_mode_catalog
from runner.extensions import discover_extensions


def main() -> int:
    discover_extensions()
    print(json.dumps(execution_mode_catalog(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
