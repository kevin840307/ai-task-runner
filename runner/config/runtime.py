"""Validated internal settings used by the running workflow."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .defaults import (
    DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_API_WAIT_TIMEOUT,
    DEFAULT_BACKEND,
    DEFAULT_FINAL_AI_REQUIRED_PASSES,
    DEFAULT_FINAL_AI_VALIDATIONS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_CYCLES,
    DEFAULT_PLANNING_TIMEOUT,
    DEFAULT_REVIEW_RETRIES,
    DEFAULT_VALIDATOR_TIMEOUT,
    DEFAULT_WATCHDOG_INTERVAL,
)

EventHandler = Callable[[dict[str, Any]], None]


def _default_workflow() -> list[dict[str, Any]]:
    from ..workflow.loader import load_workflow

    return load_workflow()


@dataclass
class RuntimeConfig:
    """Canonical, validated settings used by the running workflow."""

    goal: str = ""
    goal_file: str | None = None
    project_root: str = "."
    script: str | None = None
    validator: str | None = None
    validator_prompt: str = ""
    ai_validator_prompt: str = ""
    ai_validator_prompt_file: str | None = None
    backend: str = DEFAULT_BACKEND
    command: str | None = None
    sandbox: bool = False
    agent_args: list[str] = field(default_factory=list)
    validator_args: list[str] = field(default_factory=list)
    protect_files: list[str] = field(default_factory=list)
    validator_timeout: int = DEFAULT_VALIDATOR_TIMEOUT
    agent_timeout: int = DEFAULT_AGENT_TIMEOUT
    planning_timeout: int = DEFAULT_PLANNING_TIMEOUT
    agent_idle_after_change_timeout: float = DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT
    api_retry_timeout: float = DEFAULT_API_WAIT_TIMEOUT
    watchdog_interval: float = DEFAULT_WATCHDOG_INTERVAL
    same_session_retries: int = DEFAULT_MAX_ATTEMPTS
    review_retries: int = DEFAULT_REVIEW_RETRIES
    max_cycles: int = DEFAULT_MAX_CYCLES
    stage_retry_delay: float = 2
    api_retry_wait: float = 5
    api_retry_max_wait: float = 300
    final_ai_validations: int = DEFAULT_FINAL_AI_VALIDATIONS
    final_ai_required_passes: int = DEFAULT_FINAL_AI_REQUIRED_PASSES
    workflow: list[dict[str, Any]] = field(default_factory=_default_workflow)
    workflow_explicit: bool = False
    plugins: dict[str, dict[str, Any]] = field(default_factory=dict)
    work_dir: str = ".ai-task-runner"
    resume: bool = False
    force_new: bool = False
    plan_only: bool = False
    human_output: bool = True
    json_events: bool = False
    event_callback: EventHandler | None = None
    script_index: int | None = None
    script_total: int | None = None

    def validate(self) -> None:
        """Validate the one execution contract shared by API, CLI, and YAML."""
        from ..backends.registry import backend_names, sandbox_supported
        from ..plugins.registry import normalize_plugin_config

        if not isinstance(self.project_root, str) or not self.project_root.strip():
            raise ValueError("project_root must be a non-empty string")
        if not self.script and not self.resume and not self.goal.strip():
            raise ValueError("goal is required unless script or resume is used")
        if not self.script and not (
            isinstance(self.validator, str) and self.validator.strip()
        ):
            raise ValueError("validator is required unless script is used")
        if self.backend not in backend_names():
            raise ValueError(f"unsupported backend: {self.backend}")
        if not isinstance(self.sandbox, bool):
            raise ValueError("sandbox must be a boolean")  # noqa: TRY004
        if self.sandbox and not sandbox_supported(self.backend):
            raise ValueError(f"backend does not support sandbox mode: {self.backend}")
        if self.resume and self.force_new:
            raise ValueError("resume and force_new cannot both be true")

        work = Path(self.work_dir)
        if not self.work_dir or work.is_absolute() or ".." in work.parts:
            raise ValueError("work_dir must stay inside project_root")
        for name in ("agent_args", "validator_args", "protect_files"):
            values = getattr(self, name)
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise ValueError(f"{name} must be a list of non-empty strings")

        _positive_integer(self, "validator_timeout")
        for name in (
            "agent_timeout",
            "planning_timeout",
        ):
            _non_negative(self, name, integer=True)
        for name in ("same_session_retries", "review_retries", "max_cycles"):
            _retry_limit(self, name)
        for name in (
            "agent_idle_after_change_timeout",
            "api_retry_timeout",
            "stage_retry_delay",
            "api_retry_wait",
            "api_retry_max_wait",
        ):
            _non_negative(self, name)
        if not is_number(self.watchdog_interval) or self.watchdog_interval <= 0:
            raise ValueError("watchdog_interval must be a positive number")
        if self.api_retry_max_wait < self.api_retry_wait:
            raise ValueError("api_retry_max_wait must be greater than or equal to api_retry_wait")

        _positive_integer(self, "final_ai_validations")
        if (
            not is_integer(self.final_ai_required_passes)
            or not 0 <= self.final_ai_required_passes <= self.final_ai_validations
        ):
            raise ValueError(
                "final_ai_required_passes must be 0 or between 1 and final_ai_validations"
            )
        if not isinstance(self.plugins, dict):
            raise ValueError("plugins must be an object")  # noqa: TRY004
        if not isinstance(self.workflow, list) or not self.workflow:
            raise ValueError("workflow must be a non-empty list")
        if not isinstance(self.workflow_explicit, bool):
            raise ValueError("workflow_explicit must be a boolean")  # noqa: TRY004
        from ..workflow.loader import workflow_validators

        has_file_validation, has_ai_validation = workflow_validators(self.workflow)
        if self.validator:
            validator_is_ai = self.validator.lower() == "ai"
            if not validator_is_ai and not has_file_validation:
                raise ValueError("file validator workflow requires validate_file")
            if (validator_is_ai or self.ai_validator_prompt.strip()) and not has_ai_validation:
                raise ValueError("AI validation workflow requires validate_ai")
        self.plugins = normalize_plugin_config(self.plugins)


def _positive_integer(config: RuntimeConfig, name: str) -> None:
    value = getattr(config, name)
    if not is_integer(value) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _non_negative(config: RuntimeConfig, name: str, *, integer: bool = False) -> None:
    value = getattr(config, name)
    valid = is_integer(value) if integer else is_number(value)
    if not valid or value < 0:
        kind = "integer" if integer else "number"
        raise ValueError(f"{name} must be a non-negative {kind}")


def _retry_limit(config: RuntimeConfig, name: str) -> None:
    value = getattr(config, name)
    if not is_integer(value) or value < -1:
        raise ValueError(f"{name} must be -1 or a non-negative integer")


def is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
