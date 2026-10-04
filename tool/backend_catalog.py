#!/usr/bin/env python3
"""Print backend names and selectable model ids as JSON."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.agent import available_models, backend_names
from runner.config.defaults import DEFAULT_BACKEND


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default="")
    args = parser.parse_args(argv)
    project = Path(args.project_root).expanduser().resolve() if args.project_root else ROOT
    names = list(backend_names())
    payload = {
        "default": DEFAULT_BACKEND,
        "backends": names,
        "models": {name: available_models(name, project) for name in names},
    }
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
