#!/usr/bin/env python3
"""Print one backend's native user capability projection as JSON."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.agent import discover_capabilities
from runner.plugins.registry import discover_plugins


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--backend", required=True)
    args = parser.parse_args(argv)
    discover_plugins()
    root = Path(args.project_root).expanduser().resolve()
    try:
        values = discover_capabilities(args.backend, root)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(
        {"backend": args.backend, "capabilities": [asdict(item) for item in values]},
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
