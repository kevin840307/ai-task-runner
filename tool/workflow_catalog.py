#!/usr/bin/env python3
"""Print the data-only Workflow/Stage editor contract as JSON."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.workflow.registry import workflow_catalog


def main() -> int:
    print(json.dumps(workflow_catalog(), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
