"""Independent final AI validation Stage."""
from __future__ import annotations

from dataclasses import dataclass

from .base_stage import BaseStage, BaseStageSpec, SessionPolicy
from .contracts import MODE_READONLY, StageContext


@dataclass(frozen=True)
class AIValidatorStageSpec(BaseStageSpec):
    status: str = "正在執行最終 AI 驗證"
    run_state: str = "validating"
    mode: str = MODE_READONLY
    actor: str = "validator"
    prompt: str = "common/ai_validator.md"
    ai_validator_yolo: bool | None = None
    structured_retries: int = 2
    structured_fresh_retries: int = 1
    session_policy: SessionPolicy = "fresh"


class AIValidatorStage(BaseStage):
    ui_title = "AI Validator"
    ui_description = "Independent final AI validation with optional multi-run voting."
    ui_category = "validate"
    result_kind = "validation"
    parser_name = "validation"
    backend_mode = "review"
    client_cache_key = "ai_validation_client"
    runs_config_attr = "final_ai_validations"
    required_passes_config_attr = "final_ai_required_passes"
    result_flag = "passed"

    def _backend_mode(self, ctx: StageContext) -> str:
        return "validation" if self._yolo_enabled(ctx) else "review"

    def _augment_rendered_prompt(self, ctx: StageContext, prompt: str) -> str:
        mode = (
            "Runner final validation mode: YOLO verification is enabled. "
            "You may write small temporary verification scripts, run command-based checks, "
            "execute build/code/test commands, and run coverage validation when they materially improve evidence. "
            "Keep all scripts and generated artifacts in temporary locations or Runner work/debug/cache outputs, never in maintained project source. "
            "Do not modify production/source files, repair code, create tasks, search for tools, or ask for unavailable tools."
            if self._yolo_enabled(ctx)
            else
            "Runner final validation mode: read-only. Do not modify files, run shell/write/edit tools, create tasks, search for tools, or ask for unavailable tools. Use focused read-only checks when they materially resolve evidence."
        )
        instructions = str(getattr(ctx.config, "ai_validator_prompt", "") or "").strip()
        result = prompt.rstrip()
        result += "\n\n" + mode + "\n" if "Runner final validation mode:" not in result else "\n"
        if instructions and instructions not in result:
            result += "\nRunner-provided AI validation resource (required):\n" + instructions + "\n"
        return result

    def _yolo_enabled(self, ctx: StageContext) -> bool:
        value = self.spec.ai_validator_yolo
        if value is None:
            value = bool(getattr(ctx.config, "ai_validator_yolo", False))
        return bool(value)

    def enabled(self, ctx: StageContext) -> bool:
        return bool(
            ctx.config.workflow_explicit
            or ctx.validator_is_ai
            or ctx.config.ai_validator_prompt.strip()
        )


AIValidatorStage.spec_class = AIValidatorStageSpec

__all__ = ["AIValidatorStage", "AIValidatorStageSpec"]
