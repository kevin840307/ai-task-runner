"""Small semantic AI Stage profiles used by YAML and the UI catalog."""
from __future__ import annotations

from dataclasses import dataclass

from .base_stage import BaseStage, BaseStageSpec
from .contracts import MODE_READONLY, MODE_WRITE, StageContext


@dataclass(frozen=True)
class TaskStageSpec(BaseStageSpec):
    status: str = "AI 正在處理目前任務"
    run_state: str = "executing"
    mode: str = MODE_WRITE
    actor: str = "executor"
    prompt: str = "stages/execution.md"
    continuation_prompt: str = "stages/execution_continue.md"
    track_changes: bool = True


class TaskStage(BaseStage):
    result_kind = "task"


@dataclass(frozen=True)
class ReviewStageSpec(BaseStageSpec):
    status: str = "AI 正在確認任務是否完成"
    run_state: str = "reviewing"
    mode: str = MODE_READONLY
    actor: str = "ai"
    prompt: str = "stages/review.md"
    continuation_prompt: str = "stages/review_continue.md"
    skip_on_error: bool = True


class ReviewStage(BaseStage):
    result_kind = "review"
    semantic_failure_threshold = 2
    parser_name = "review"
    backend_mode = "review"
    timeout_config_attr = "planning_timeout"
    retry_config_attr = "review_retries"
    client_cache_key = "review_client"

    def result_status(self, data) -> str:
        return "pass" if bool(data["completed"]) else "fail"


@dataclass(frozen=True)
class AIValidatorStageSpec(BaseStageSpec):
    status: str = "正在執行最終 AI 驗證"
    run_state: str = "validating"
    mode: str = MODE_READONLY
    actor: str = "validator"
    prompt: str = "stages/ai_validator.md"
    structured_retries: int = 2
    structured_fresh_retries: int = 1
    retry: int | None = -1
    fresh_session_each_run: bool = True


class AIValidatorStage(BaseStage):
    result_kind = "validation"
    parser_name = "validation"
    backend_mode = "review"
    client_cache_key = "ai_validation_client"
    runs_config_attr = "final_ai_validations"
    required_passes_config_attr = "final_ai_required_passes"

    def enabled(self, ctx: StageContext) -> bool:
        # An explicit Workflow owns its validation topology: if ai_validator is
        # present in that Workflow, its presence is the user's intent to run it.
        # Legacy/default workflow selection still uses validator/AI-prompt gates.
        return bool(ctx.config.workflow_explicit or ctx.validator_is_ai or ctx.config.ai_validator_prompt.strip())

    def result_status(self, data) -> str:
        return "pass" if bool(data["passed"]) else "fail"


TaskStage.spec_class = TaskStageSpec
ReviewStage.spec_class = ReviewStageSpec
AIValidatorStage.spec_class = AIValidatorStageSpec

__all__ = [
    "AIValidatorStage",
    "AIValidatorStageSpec",
    "ReviewStage",
    "ReviewStageSpec",
    "TaskStage",
    "TaskStageSpec",
]
