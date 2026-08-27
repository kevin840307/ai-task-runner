"""Shared prompt input helper for fake Qwen/OpenCode CLIs used by tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

PromptStage = Literal[
    "plan_finalize",
    "plan_judge",
    "plan_refine",
    "execute",
    "review",
    "review_finalize",
    "validator",
    "unknown",
]


def read_prompt(args: list[str]) -> tuple[bool, str]:
    is_qwen = "--output-format" in args and "stream-json" in args
    prompt = sys.stdin.buffer.read().decode("utf-8")
    return is_qwen, prompt


def prompt_stage(prompt: str) -> PromptStage:
    """Classify Runner prompts by stable workflow contract, in one test helper."""
    if "plan quality judge" in prompt:
        return "plan_judge"
    if "Continue the existing planning work" in prompt:
        return "plan_refine"
    if (
        "Create the implementation plan now" in prompt
        or "Create the initial implementation plan now" in prompt
        or "Create the repair implementation plan now" in prompt
        or "Plan only the remaining work" in prompt
    ):
        return "plan_finalize"
    if "Review only. Finalize the current review now." in prompt:
        return "review_finalize"
    if (
        "Review only. You are a read-only task reviewer" in prompt
        or "Review only. Read-only: do not modify project files." in prompt
        or "Continue the same review stage." in prompt
    ):
        return "review"
    if (
        "Final validation in a fresh independent session" in prompt
        or "Final validation. This is a fresh independent read-only session." in prompt
    ):
        return "validator"
    if any(
        marker in prompt
        for marker in (
            "Current TODO is the only executable scope",
            "Work only on this Current TODO",
            "Continue only the same current TODO",
            "Continue the current task. Fix the previous failure and finish it.",
            "Continue the same execute stage.",
            "Continue the same repair stage.",
            "Workflow Stage instructions:",
        )
    ):
        return "execute"
    return "unknown"


def record_prompt(
    directory: Path,
    stage: PromptStage,
    prompt: str,
    args: list[str],
) -> None:
    """Record model-call evidence for end-to-end flow assertions."""
    record = {
        "stage": stage,
        "chars": len(prompt),
        "resumed": "--resume" in args or "--session" in args,
        "prompt": prompt,
    }
    with (directory / "prompt-log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
