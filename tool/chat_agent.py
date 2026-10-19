#!/usr/bin/env python3
"""Run one ordinary Project Chat turn through the canonical Agent adapter."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.agent import (
    BackendError,
    chat_features,
    configure_interaction_args,
    configure_model_args,
    create_backend,
    ensure_native_session,
    normalize_ask_request,
    pending_native_ask,
    resolve_native_ask,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--mode", choices=("read", "auto", "yolo"), default="auto")
    parser.add_argument("--reasoning", default="")
    parser.add_argument("--session", default="")
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args(argv)

    prompt = sys.stdin.read()
    if not prompt.strip():
        print(json.dumps({"error": "Chat message is empty"}))
        return 2

    project = Path(args.project_root).expanduser().resolve()
    try:
        extra_args = configure_interaction_args(args.backend, args.mode, [])
        extra_args = configure_model_args(args.backend, extra_args, args.model)
        backend = create_backend(
            args.backend,
            None,
            project,
            extra_args,
            timeout=args.timeout,
        )
        backend.configure_interaction(args.mode)
        backend.configure_reasoning(args.reasoning)
        result = backend.ask(prompt, args.session)
    except (BackendError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps({
        "text": result.text,
        "session_id": result.session_id or args.session,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
