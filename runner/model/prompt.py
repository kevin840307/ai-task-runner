"""Shared model prompt composition."""
from __future__ import annotations
from pathlib import Path
from ..config.project_policy import instructions
from ..extensions.base import extension_instructions
from ..utils.templates import render_resource
from ..prompts import SYSTEM_PACKAGE

def always_instructions(root: Path) -> str:
    text = instructions(root, "always")
    return f"\nUser-enforced instructions (apply to this call):\n{text}\n" if text else ""

def model_rules(root: Path) -> str:
    return render_resource(SYSTEM_PACKAGE, "rules.md", {"root": root, "extension_rules": extension_instructions(root)}) + always_instructions(root)

def structured_retry_prompt(error: str) -> str:
    return render_resource(SYSTEM_PACKAGE, "structured_output_retry.md", {"error": error.strip()[-500:] or "invalid structured output"})

__all__ = ["always_instructions", "model_rules", "structured_retry_prompt"]
