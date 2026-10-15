#!/usr/bin/env python3
"""Generate a preview-only ordered Task List using the canonical agent/structured paths."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.agent import create_ai_client
from runner.agent.structured import parse_result, require_object, require_text, structured_call
from runner.config.defaults import DEFAULT_BACKEND
from runner.config.runtime import RuntimeConfig
from runner.errors import RunnerError
from runner.plugins.registry import discover_plugins

MAX_ITEMS = 40
MAX_CONTEXT_CHARS = 20_000


def _parse_payload(raw: str) -> list[dict[str, str]]:
    def parse(value: Any) -> list[dict[str, str]]:
        obj = require_object(value)
        items = obj.get("items")
        if not isinstance(items, list) or not items:
            raise RunnerError("items must be a non-empty array")
        if len(items) > MAX_ITEMS:
            raise RunnerError(f"items must contain at most {MAX_ITEMS} entries")
        result: list[dict[str, str]] = []
        for index, item in enumerate(items, 1):
            row = require_object(item)
            instruction = require_text(row.get("instruction"), f"items[{index}].instruction")
            if len(instruction) > 20_000:
                raise RunnerError(f"items[{index}].instruction is too long")
            result.append({"instruction": instruction})
        return result
    return parse_result(raw, parse)


def _context(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    parts: list[str] = []
    used = 0
    for item in reversed(messages[-30:]):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        text = str(item.get("text") or "").strip()
        if role not in {"user", "assistant"} or not text:
            continue
        line = f"{role}: {text}"
        if parts and used + len(line) > MAX_CONTEXT_CHARS:
            break
        parts.append(line)
        used += len(line)
    return "\n".join(reversed(parts))


def run(request: dict[str, Any], project: Path, backend: str, model: str) -> dict[str, Any]:
    request_text = str(request.get("request") or "").strip()
    if not request_text:
        raise ValueError("Task List request is empty")
    config = RuntimeConfig(
        goal="task list preview",
        project_root=str(project),
        backend=backend,
        force_new=True,
        auto_register_ui_project=False,
        human_output=False,
    )
    client = create_ai_client(
        config,
        project,
        mode="planning",
        session_id="",
        timeout=180,
        allow_project_read=True,
        model_override=model,
    )
    context = _context(request.get("history"))
    prompt = (
        "Create an ordered development Task List preview for the user's request. "
        "You may inspect the bound project read-only when useful. Do not edit files or run the Task. "
        "Split work into small independently understandable instructions, ordered by dependency. "
        "Return exactly one JSON object shaped as "
        '{"items":[{"instruction":"..."}]}. '
        f"Use at most {MAX_ITEMS} items.\n\n"
        + (f"Recent conversation:\n{context}\n\n" if context else "")
        + f"Request:\n{request_text}"
    )
    items = structured_call(
        prompt,
        _parse_payload,
        lambda value: client.ask(value, timeout=180),
        retries=1,
    )
    return {
        "items": items,
        "backend": str(client.backend or backend),
        "model": str(client.model or model),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a Task List preview")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    parser.add_argument("--model", default="")
    args = parser.parse_args(argv)
    project = Path(args.project_root).expanduser().resolve()
    try:
        if not project.is_dir():
            raise ValueError("project root does not exist")
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        discover_plugins()
        print(json.dumps(run(request, project, args.backend, args.model), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
