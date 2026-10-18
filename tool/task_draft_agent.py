#!/usr/bin/env python3
"""Generate one structured TaskDraft payload through the canonical Agent adapter."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.agent import BackendError, configure_interaction_args, configure_model_args, create_backend

PROMPT_FILE = ROOT / "ui" / "task_draft_prompt.md"


def _extract_object(text: str) -> dict:
    raw = str(text or "").strip()
    fence = chr(96) * 3
    candidates = [raw]
    if fence in raw:
        candidates.extend(raw.split(fence))
    for candidate in candidates:
        value = candidate.strip()
        if value.lower().startswith("json"):
            value = value[4:].lstrip()
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            start, end = value.find("{"), value.rfind("}")
            if start < 0 or end <= start:
                continue
            try:
                parsed = json.loads(value[start:end + 1])
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("TaskDraft Agent did not return one JSON object")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--reasoning", default="")
    parser.add_argument("--draft-mode", choices=("auto", "single", "list"), required=True)
    args = parser.parse_args(argv)
    spec = sys.stdin.read().strip()
    if not spec:
        print(json.dumps({"error": "TaskDraft spec is empty"}))
        return 2
    try:
        prompt = (
            PROMPT_FILE.read_text(encoding="utf-8").rstrip()
            + "\n\nSelected mode: " + args.draft_mode
            + "\n\nUser specification:\n" + spec + "\n"
        )
        extra_args = configure_interaction_args(args.backend, "read", [])
        extra_args = configure_model_args(args.backend, extra_args, args.model)
        backend = create_backend(
            args.backend, None, Path(args.project_root).expanduser().resolve(),
            extra_args, timeout=1800,
        )
        backend.configure_interaction("read")
        backend.configure_reasoning(args.reasoning)
        result = backend.ask(prompt, "")
        payload = _extract_object(result.text)
    except (BackendError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"draft": payload}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
