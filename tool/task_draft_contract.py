"""Shared TaskDraft subprocess contract without importing Runner runtime."""
from __future__ import annotations

TASK_DRAFT_AGENT_TIMEOUT_SECONDS = 1800
TASK_DRAFT_WRAPPER_GRACE_SECONDS = 60
TASK_DRAFT_ERROR_CHARS = 4000

__all__ = [
    "TASK_DRAFT_AGENT_TIMEOUT_SECONDS",
    "TASK_DRAFT_WRAPPER_GRACE_SECONDS",
    "TASK_DRAFT_ERROR_CHARS",
]
