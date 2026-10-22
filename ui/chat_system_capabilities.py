"""Runner-owned Project Chat system capability projection."""
from __future__ import annotations

from typing import Any

SYSTEM_COMMANDS = (
    {
        "token": "@ask-demo",
        "name": "ask-demo",
        "description": "Open a deterministic clarification card for testing the Ask UX.",
        "kind": "chat_test_command",
        "source": "Chat",
        "user_invocable": True,
        "enabled": True,
        "permission": "explicit",
        "availability": "available",
    },
    {
        "token": "@goal",
        "name": "goal",
        "description": "Create one durable Task and run it immediately.",
        "kind": "runner_command",
        "source": "Runner",
        "user_invocable": True,
        "enabled": True,
        "permission": "explicit",
        "availability": "available",
    },
    {
        "token": "@task",
        "name": "task",
        "description": "Generate a TaskDraft; AI chooses one Task or an ordered Task List.",
        "kind": "runner_command",
        "source": "Runner",
        "user_invocable": True,
        "enabled": True,
        "permission": "explicit",
        "availability": "available",
    },
    {
        "token": "@task-single",
        "name": "task-single",
        "description": "Generate exactly one TaskDraft item.",
        "kind": "runner_command",
        "source": "Runner",
        "user_invocable": True,
        "enabled": True,
        "permission": "explicit",
        "availability": "available",
    },
    {
        "token": "@task-list",
        "name": "task-list",
        "description": "Generate two or more ordered TaskDraft items.",
        "kind": "runner_command",
        "source": "Runner",
        "user_invocable": True,
        "enabled": True,
        "permission": "explicit",
        "availability": "available",
    },
)


def system_capabilities(studio_files: dict[str, Any]) -> dict[str, Any]:
    values = [dict(item) for item in SYSTEM_COMMANDS]
    prompts = studio_files.get("prompts")
    if isinstance(prompts, list):
        for item in prompts:
            if not isinstance(item, dict):
                continue
            name = str(item.get("display_name") or item.get("name") or "").strip()
            file_id = str(item.get("id") or "").strip()
            if not name or not file_id:
                continue
            values.append({
                "token": f"@prompt:{file_id}",
                "name": name,
                "description": "Prompt asset reference. Use it from Task Editor / Workflow Studio.",
                "kind": "prompt",
                "source": str(item.get("scope") or "asset"),
                "user_invocable": False,
                "enabled": False,
                "permission": "reference",
                "availability": "task_editor_only",
            })
    return {"capabilities": values}
