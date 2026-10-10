"""Canonical editable Workflow and Prompt asset roots."""
from pathlib import Path

ASSET_ROOT = Path(__file__).resolve().parent
WORKFLOW_DIR = ASSET_ROOT / "workflows"
PROMPT_DIR = ASSET_ROOT / "prompts"

__all__ = ["ASSET_ROOT", "WORKFLOW_DIR", "PROMPT_DIR"]
