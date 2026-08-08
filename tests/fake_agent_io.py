"""Shared prompt input helper for fake Qwen/OpenCode CLIs used by tests."""
from __future__ import annotations

import sys


def read_prompt(args: list[str]) -> tuple[bool, str]:
    is_qwen = "--output-format" in args and "stream-json" in args
    return is_qwen, sys.stdin.read() if is_qwen else args[-1]
