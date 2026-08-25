"""Bundled Stage presets and workflow topology."""

_PLAN = {
    "stage": "plan",
    "run_state": "planning",
    "mode": "readonly",
    "backend_mode": "planning",
    "timeout_attr": "planning_timeout",
    "result_handler": "handle_plan_result",
}

_EXECUTION = {
    "stage": "ai",
    "run_state": "executing",
    "mode": "write",
    "actor": "executor",
    "track_changes": True,
    "prompt": "stages/execution.md",
}

STAGES = {
    "plan": {
        **_PLAN,
        "name": "planning",
        "status": "AI 正在產生任務規劃",
        "plan_only_stop": True,
    },
    "repair_plan": {
        **_PLAN,
        "status": "AI 正在建立修復規劃",
        "repair_plan": True,
        "fresh_session_on_start": True,
    },
    "execute": {
        **_EXECUTION,
        "status": "AI 正在處理目前任務",
        "result_handler": "handle_execute_result",
    },
    "repair": {
        **_EXECUTION,
        "status": "AI 正在修復目前任務",
        "result_handler": "handle_repair_result",
    },
    "run_prompt": {
        **_EXECUTION,
        "status": "AI 正在執行 Workflow Prompt",
        "prompt": "stages/workflow_prompt.md",
        "result_handler": "handle_prompt_result",
    },
    "review": {
        "stage": "ai",
        "status": "AI 正在執行 Workflow Review",
        "run_state": "reviewing",
        "mode": "readonly",
        "backend_mode": "review",
        "client_cache_key": "workflow_review_client",
        "timeout_attr": "planning_timeout",
        "prompt": "stages/workflow_review.md",
        "parser": "parse_review",
        "result_status": "completed_status",
        "result_handler": "handle_workflow_review_result",
    },
    "task_review": {
        "stage": "ai",
        "name": "review",
        "status": "AI 正在確認任務是否完成",
        "run_state": "reviewing",
        "mode": "readonly",
        "backend_mode": "review",
        "client_cache_key": "review_client",
        "timeout_attr": "planning_timeout",
        "prompt": "stages/review.md",
        "parser": "parse_review",
        "result_status": "completed_status",
        "result_handler": "handle_review_result",
        "retry_attr": "review_retries",
        "skip_on_error": True,
    },
    "validate_file": {
        "stage": "python_validator",
        "status": "正在執行 File Validator",
        "run_state": "validating",
        "mode": "write",
        "actor": "validator",
        "result_handler": "handle_validation_result",
    },
    "validate_ai": {
        "stage": "ai",
        "status": "正在執行最終 AI 驗證",
        "run_state": "validating",
        "mode": "readonly",
        "actor": "validator",
        "condition": "needs_ai_validation",
        "client_cache_key": "ai_validation_client",
        "fresh_session_each_run": True,
        "structured_retries": 2,
        "structured_fresh_retries": 1,
        "retry": -1,
        "runs_field": "final_ai_validations",
        "required_passes_field": "final_ai_required_passes",
        "prompt": "stages/ai_validator.md",
        "parser": "parse_ai_validation_stage",
        "result_status": "validation_status",
        "result_handler": "handle_final_validation_result",
    },
}

FLOWS = {
    "default": ["plan", "validate_file", "validate_ai"],
    "todo": ["execute", "task_review"],
    "repair": ["repair", "task_review"],
    "validators": ["validate_file", "validate_ai"],
    "replan": ["plan", "validate_file", "validate_ai"],
    "validator_repair": ["repair_plan", "validate_file", "validate_ai"],
}

__all__ = ["FLOWS", "STAGES"]
