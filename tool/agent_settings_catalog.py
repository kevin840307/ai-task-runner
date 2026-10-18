#!/usr/bin/env python3
"""Print Agent-owned Project Chat settings choices as JSON."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.agent import (
    BackendError,
    available_models,
    interaction_modes,
    reasoning_options,
)
from runner.plugins.registry import discover_plugins


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--model", default="")
    args = parser.parse_args(argv)
    root = Path(args.project_root).expanduser().resolve()
    discover_plugins()
    try:
        models = available_models(args.backend, root)
        try:
            modes = interaction_modes(args.backend)
        except BackendError:
            modes = ()
        reasoning = reasoning_options(args.backend, root, args.model)
    except BackendError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "agent": args.backend,
        "models": models,
        "modes": [asdict(item) for item in modes],
        "reasoning": [asdict(item) for item in reasoning],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
