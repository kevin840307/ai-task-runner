"""Single registration point for Workflow Stage YAML and construction."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import RunnerError

StageConfigurer = Callable[[dict[str, Any], dict[str, Any], Path, int], None]
GLOBAL_OPTIONS = frozenset({"restart_at"})


@dataclass(frozen=True)
class StageRegistration:
    name: str
    stage_class: str
    spec_class: str
    defaults: dict[str, Any]
    options: frozenset[str] = frozenset()
    configure: StageConfigurer | None = None
    public: bool = True


STAGE_REGISTRY: dict[str, StageRegistration] = {}


def register_stage(registration: StageRegistration) -> None:
    if registration.name in STAGE_REGISTRY:
        raise ValueError(f"duplicate Stage registration: {registration.name}")
    STAGE_REGISTRY[registration.name] = registration


def stage_definition(
    name: str,
    options: dict[str, Any] | None = None,
    *,
    source: Path | None = None,
    index: int = 0,
) -> dict[str, Any]:
    registration = _registration(name, public=source is not None)
    supplied = dict(options or {})
    stage_options = {
        key: value for key, value in supplied.items() if key not in GLOBAL_OPTIONS
    }
    unknown = sorted(
        str(key) for key in stage_options if key not in registration.options
    )
    if unknown:
        raise RunnerError(
            f"workflow stage {index} unknown options: {', '.join(unknown)}"
        )
    values = deepcopy(registration.defaults)
    values["stage"] = name
    values.setdefault("name", name)
    if registration.configure is not None:
        registration.configure(values, stage_options, source or Path.cwd(), index)
    elif stage_options:
        values.update(stage_options)
    if "restart_at" in supplied:
        values["restart_at"] = _positive(supplied["restart_at"], index, "restart_at")
    return values


def create_stage(definition: dict[str, Any]):
    values = deepcopy(definition)
    values.pop("_workflow_index", None)
    name = str(values.pop("stage", ""))
    restart_at = values.pop("restart_at", None)
    registration = _registration(name)
    stage_class = _import_symbol(registration.stage_class)
    spec_class = _import_symbol(registration.spec_class)

    from .result_parsers import PARSERS
    from .rules import CONDITIONS, RESULT_HANDLERS, STATUS_RESOLVERS

    for field, mapping in {
        "result_handler": RESULT_HANDLERS,
        "parser": PARSERS,
        "result_status": STATUS_RESOLVERS,
        "condition": CONDITIONS,
    }.items():
        value = values.get(field)
        if isinstance(value, str):
            try:
                values[field] = mapping[value]
            except KeyError as error:
                raise ValueError(f"unknown {field}: {value}") from error
    stage = stage_class(spec_class(**values))
    stage.restart_at = restart_at
    return stage


def _registration(name: str, *, public: bool = False) -> StageRegistration:
    try:
        registration = STAGE_REGISTRY[name]
    except KeyError as error:
        raise RunnerError(f"unknown workflow stage: {name}") from error
    if public and not registration.public:
        raise RunnerError(f"unknown workflow stage: {name}")
    return registration


def _import_symbol(reference: str):
    module_name, symbol = reference.split(":", 1)
    return getattr(importlib.import_module(module_name), symbol)


def _read_prompt(options: dict[str, Any], source: Path, index: int) -> str:
    prompt = options.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise RunnerError(f"workflow stage {index} requires a non-empty prompt")
    path = Path(prompt).expanduser()
    if not path.is_absolute():
        path = source.parent / path
    try:
        instructions = path.read_text(encoding="utf-8-sig").strip()
    except OSError as error:
        raise RunnerError(
            f"workflow stage {index} prompt not found: {prompt}"
        ) from error
    if not instructions:
        raise RunnerError(f"workflow stage {index} prompt must not be empty")
    return instructions


def _retry(value: Any, index: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < -1:
        raise RunnerError(
            f"workflow stage {index} retry must be -1 or a non-negative integer"
        )
    return value


def _positive(value: Any, index: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RunnerError(f"workflow stage {index} {name} must be a positive integer")
    return value


def _configure_retry(
    values: dict[str, Any],
    options: dict[str, Any],
    _source: Path,
    index: int,
) -> None:
    if "retry" in options:
        values["retry"] = _retry(options["retry"], index)
        if "retry_attr" in values:
            values["retry_attr"] = ""


def _configure_ai(
    values: dict[str, Any],
    options: dict[str, Any],
    source: Path,
    index: int,
) -> None:
    mode = options.get("mode", "write")
    if mode not in {"write", "review"}:
        raise RunnerError(f"workflow stage {index} mode must be write or review")
    values["instructions"] = _read_prompt(options, source, index)
    if mode == "review":
        values.update(_WORKFLOW_REVIEW)
    elif "skip" in options:
        raise RunnerError(f"workflow stage {index} skip requires mode: review")
    _configure_retry(values, options, source, index)
    if "skip" in options:
        if not isinstance(options["skip"], bool):
            raise RunnerError(f"workflow stage {index} skip must be boolean")
        values["skip_on_error"] = options["skip"]


def _configure_final_ai(
    values: dict[str, Any],
    options: dict[str, Any],
    source: Path,
    index: int,
) -> None:
    if "prompt" in options:
        values["instructions"] = _read_prompt(options, source, index)
    _configure_retry(values, options, source, index)
    if "runs" in options:
        values["runs"] = _positive(options["runs"], index, "runs")
        values["runs_field"] = ""
    if "required_passes" in options:
        required = options["required_passes"]
        if not isinstance(required, int) or isinstance(required, bool) or required < 0:
            raise RunnerError(
                f"workflow stage {index} required_passes must be a non-negative integer"
            )
        values["required_passes"] = required
        values["required_passes_field"] = ""
    if (
        "runs" in options
        and "required_passes" in options
        and options["required_passes"] > options["runs"]
    ):
        raise RunnerError(f"workflow stage {index} required_passes cannot exceed runs")


_AI_CLASS = "runner.workflow.stages.ai_stage:AIStage"
_AI_SPEC = "runner.workflow.stages.ai_stage:AIStageSpec"
_PLAN_CLASS = "runner.workflow.stages.plan_stage:PlanStage"
_PLAN_SPEC = "runner.workflow.stages.plan_stage:PlanStageSpec"
_FILE_CLASS = "runner.workflow.stages.python_validator:PythonValidatorStage"
_FILE_SPEC = "runner.workflow.stages.python_validator:PythonValidatorStageSpec"

_EXECUTION = {
    "status": "AI 正在處理 Workflow Prompt",
    "run_state": "executing",
    "mode": "write",
    "actor": "executor",
    "track_changes": True,
    "prompt": "stages/workflow_prompt.md",
    "result_handler": "handle_prompt_result",
}
_WORKFLOW_REVIEW = {
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
}
_PLAN = {
    "run_state": "planning",
    "mode": "readonly",
    "actor": "ai",
    "backend_mode": "planning",
    "timeout_attr": "planning_timeout",
    "result_handler": "handle_plan_result",
}


def _register_builtins() -> None:
    registrations = (
        StageRegistration(
            "ai",
            _AI_CLASS,
            _AI_SPEC,
            _EXECUTION,
            frozenset({"prompt", "mode", "retry", "skip"}),
            _configure_ai,
        ),
        StageRegistration(
            "planning",
            _PLAN_CLASS,
            _PLAN_SPEC,
            {
                **_PLAN,
                "name": "planning",
                "status": "AI 正在產生任務規劃",
                "plan_only_stop": True,
            },
            frozenset({"retry"}),
            _configure_retry,
        ),
        StageRegistration(
            "validate_file",
            _FILE_CLASS,
            _FILE_SPEC,
            {
                "status": "正在執行 File Validator",
                "run_state": "validating",
                "mode": "write",
                "actor": "validator",
                "result_handler": "handle_validation_result",
            },
            frozenset({"retry"}),
            _configure_retry,
        ),
        StageRegistration(
            "validate_ai",
            _AI_CLASS,
            _AI_SPEC,
            {
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
            frozenset({"prompt", "retry", "runs", "required_passes"}),
            _configure_final_ai,
        ),
        StageRegistration(
            "repair_plan",
            _PLAN_CLASS,
            _PLAN_SPEC,
            {
                **_PLAN,
                "status": "AI 正在建立修復規劃",
                "repair_plan": True,
                "fresh_session_on_start": True,
            },
            public=False,
        ),
        StageRegistration(
            "execute",
            _AI_CLASS,
            _AI_SPEC,
            {
                **_EXECUTION,
                "status": "AI 正在處理目前任務",
                "prompt": "stages/execution.md",
                "result_handler": "handle_execute_result",
            },
            public=False,
        ),
        StageRegistration(
            "repair",
            _AI_CLASS,
            _AI_SPEC,
            {
                **_EXECUTION,
                "status": "AI 正在修復目前任務",
                "prompt": "stages/execution.md",
                "result_handler": "handle_repair_result",
            },
            public=False,
        ),
        StageRegistration(
            "task_review",
            _AI_CLASS,
            _AI_SPEC,
            {
                **_WORKFLOW_REVIEW,
                "name": "review",
                "status": "AI 正在確認任務是否完成",
                "client_cache_key": "review_client",
                "prompt": "stages/review.md",
                "result_handler": "handle_review_result",
                "retry_attr": "review_retries",
                "skip_on_error": True,
            },
            public=False,
        ),
    )
    for registration in registrations:
        register_stage(registration)


_register_builtins()

__all__ = [
    "STAGE_REGISTRY",
    "StageRegistration",
    "create_stage",
    "register_stage",
    "stage_definition",
]
