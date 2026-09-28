from pathlib import Path

"""Prompt templates live beside Workflow YAML assets."""

PROMPT_ROOT = Path(__file__).resolve().parents[1] / "workflows"

__all__ = ["PROMPT_ROOT"]
