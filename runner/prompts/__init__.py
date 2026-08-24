from pathlib import Path

"""Bundled prompt resource locations."""

PROMPT_ROOT = Path(__file__).resolve().parent
SYSTEM_PACKAGE = "runner.prompts.system"
STAGE_PACKAGE = "runner.prompts.stages"

__all__ = ["PROMPT_ROOT", "STAGE_PACKAGE", "SYSTEM_PACKAGE"]
