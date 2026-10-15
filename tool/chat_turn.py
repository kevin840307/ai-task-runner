#!/usr/bin/env python3
"""One bounded, read-only conversational turn over the canonical backend adapter."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.agent import AIError, create_ai_client
from runner.config.defaults import DEFAULT_BACKEND
from runner.config.runtime import RuntimeConfig
from runner.plugins.registry import discover_plugins

MAX_HISTORY_MESSAGES = 40
MAX_HISTORY_CHARS = 40_000
CHAT_TIMEOUT_SECONDS = 180


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run one read-only project Chat turn")
    value.add_argument("--project-root", required=True)
    value.add_argument("--backend", default=DEFAULT_BACKEND)
    value.add_argument("--model", default="")
    value.add_argument("--session-id", default="")
    return value


def _bounded_history(messages: Any) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        return []
    rows: list[dict[str, str]] = []
    used = 0
    for raw in reversed(messages[-MAX_HISTORY_MESSAGES:]):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "")
        text = str(raw.get("text") or "")
        if role not in {"user", "assistant"} or not text:
            continue
        encoded = len(text)
        if rows and used + encoded > MAX_HISTORY_CHARS:
            break
        rows.append({"role": role, "text": text[-MAX_HISTORY_CHARS:]})
        used += min(encoded, MAX_HISTORY_CHARS)
    rows.reverse()
    return rows


def _fresh_prompt(message: str, history: list[dict[str, str]]) -> str:
    transcript = "\n".join(
        f"{row['role'].capitalize()}: {row['text']}" for row in history
    )
    if transcript:
        transcript += "\n"
    return (
        "You are the read-only project Chat assistant. Discuss, explain, inspect, and analyze "
        "the bound project when useful. Do not edit files, run destructive commands, start a "
        "Task, or claim work was executed. Answer the user's latest message directly.\n\n"
        f"Recent conversation:\n{transcript}"
        f"User: {message}\nAssistant:"
    )


def _followup_prompt(message: str) -> str:
    return (
        "Continue the same read-only project conversation. "
        "Do not modify files or start a Task.\n\n"
        f"User: {message}\nAssistant:"
    )


def run_chat(
    request: dict[str, Any],
    *,
    project: Path,
    backend: str,
    model: str,
    session_id: str,
    client_factory=create_ai_client,
) -> dict[str, Any]:
    message = str(request.get("message") or "").strip()
    if not message:
        raise ValueError("Chat message is empty")
    if len(message) > 20_000:
        raise ValueError("Chat message is too long")
    history = _bounded_history(request.get("history"))
    config = RuntimeConfig(
        goal="project chat",
        project_root=str(project),
        backend=backend,
        force_new=True,
        auto_register_ui_project=False,
        human_output=False,
    )

    def make_client(current_session: str):
        return client_factory(
            config,
            project,
            mode="planning",
            session_id=current_session,
            timeout=CHAT_TIMEOUT_SECONDS,
            allow_project_read=True,
            model_override=model,
        )

    client = make_client(session_id)
    prompt = _followup_prompt(message) if session_id else _fresh_prompt(message, history)
    try:
        output = client.ask(prompt, timeout=CHAT_TIMEOUT_SECONDS)
    except AIError:
        # A backend-invalidated session is rebuilt once from bounded durable Chat
        # history. Other model/service errors remain visible to the user.
        if not session_id or client.session_id:
            raise
        client = make_client("")
        output = client.ask(_fresh_prompt(message, history), timeout=CHAT_TIMEOUT_SECONDS)
    return {
        "text": str(output or "").strip(),
        "session_id": str(client.session_id or ""),
        "backend": str(client.backend or backend),
        "model": str(client.model or model),
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    project = Path(args.project_root).expanduser().resolve()
    if not project.is_dir():
        raise SystemExit("project root does not exist")
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        discover_plugins()
        result = run_chat(
            request,
            project=project,
            backend=str(args.backend),
            model=str(args.model),
            session_id=str(args.session_id),
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
