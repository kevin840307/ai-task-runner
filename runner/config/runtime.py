"""Validated internal settings used by the running workflow."""
from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .defaults import (
    DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_API_WAIT_TIMEOUT,
    DEFAULT_BACKEND,
    DEFAULT_FINAL_AI_REQUIRED_PASSES,
    DEFAULT_FINAL_AI_VALIDATIONS,
    DEFAULT_LOOP_CONTEXT_COMPRESS,
    DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_CYCLES,
    DEFAULT_PLANNING_TIMEOUT,
    DEFAULT_REVIEW_RETRIES,
    DEFAULT_VALIDATOR_TIMEOUT,
    DEFAULT_WATCHDOG_INTERVAL,
)

EventHandler = Callable[[dict[str, Any]], None]


@dataclass
class RuntimeConfig:
    """Canonical execution settings; CLI aliases are adapted at the boundary."""

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
    loop_context_compress: bool = DEFAULT_LOOP_CONTEXT_COMPRESS
    loop_context_compress_threshold: float = DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD
    work_dir: str = ".ai-task-runner"
    resume: bool = False
    force_new: bool = False
    plan_only: bool = False
    human_output: bool = True
    json_events: bool = False
    event_callback: EventHandler | None = None
    script_index: int | None = None
    script_total: int | None = None

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> RuntimeConfig:
        """Adapt CLI/legacy Namespace names into the canonical internal contract."""
        json_events = bool(getattr(args, "json_events", False))
        return cls(
            goal=getattr(args, "goal", "") or "",
            goal_file=getattr(args, "goal_file", None),
            project_root=getattr(args, "project_root", "."),
            script=getattr(args, "script", None),
            validator=getattr(args, "validator", None),
            validator_prompt=getattr(args, "validator_prompt", ""),
            ai_validator_prompt=getattr(args, "ai_validator_prompt", ""),
            ai_validator_prompt_file=getattr(args, "ai_validator_prompt_file", None),
            backend=getattr(args, "backend", DEFAULT_BACKEND),
            command=getattr(args, "command", None),
            sandbox=bool(getattr(args, "sandbox", False)),
            agent_args=list(getattr(args, "agent_args", getattr(args, "agent_arg", []))),
            validator_args=list(getattr(args, "validator_args", getattr(args, "validator_arg", []))),
            protect_files=list(getattr(args, "protect_files", getattr(args, "protect_file", []))),
            validator_timeout=getattr(args, "validator_timeout", DEFAULT_VALIDATOR_TIMEOUT),
            agent_timeout=getattr(args, "agent_timeout", DEFAULT_AGENT_TIMEOUT),
            planning_timeout=getattr(args, "planning_timeout", DEFAULT_PLANNING_TIMEOUT),
            agent_idle_after_change_timeout=getattr(
                args,
                "agent_idle_after_change_timeout",
                DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
            ),
            api_retry_timeout=getattr(args, "api_retry_timeout", getattr(args, "api_wait_timeout", DEFAULT_API_WAIT_TIMEOUT)),
            watchdog_interval=getattr(args, "watchdog_interval", DEFAULT_WATCHDOG_INTERVAL),
            same_session_retries=getattr(
                args,
                "same_session_retries",
                getattr(args, "task_recovery_threshold", getattr(args, "max_attempts", DEFAULT_MAX_ATTEMPTS)),
            ),
            review_retries=getattr(args, "review_retries", DEFAULT_REVIEW_RETRIES),
            max_cycles=getattr(
                args,
                "max_cycles",
                getattr(args, "full_replan_threshold", DEFAULT_MAX_CYCLES),
            ),
            stage_retry_delay=getattr(args, "stage_retry_delay", getattr(args, "retry_delay", 2)),
            api_retry_wait=getattr(args, "api_retry_wait", getattr(args, "retry_wait", 5)),
            api_retry_max_wait=getattr(args, "api_retry_max_wait", getattr(args, "retry_max_wait", 300)),
            final_ai_validations=getattr(args, "final_ai_validations", DEFAULT_FINAL_AI_VALIDATIONS),
            final_ai_required_passes=getattr(
                args,
                "final_ai_required_passes",
                DEFAULT_FINAL_AI_REQUIRED_PASSES,
            ),
            loop_context_compress=getattr(args, "loop_context_compress", DEFAULT_LOOP_CONTEXT_COMPRESS),
            loop_context_compress_threshold=getattr(
                args,
                "loop_context_compress_threshold",
                DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD,
            ),
            work_dir=getattr(args, "work_dir", ".ai-task-runner"),
            resume=bool(getattr(args, "resume", False)),
            force_new=bool(getattr(args, "force_new", False)),
            plan_only=bool(getattr(args, "plan_only", False)),
            human_output=bool(getattr(args, "human_output", not json_events)),
            json_events=json_events,
            event_callback=getattr(args, "event_callback", None),
            script_index=getattr(args, "script_index", None),
            script_total=getattr(args, "script_total", None),
        )

    def to_namespace(self) -> argparse.Namespace:
        """Expose legacy CLI field names only at the compatibility boundary."""
        values = vars(self).copy()
        values.update({
            "agent_arg": list(self.agent_args),
            "validator_arg": list(self.validator_args),
            "protect_file": list(self.protect_files),
            "api_wait_timeout": self.api_retry_timeout,
            "task_recovery_threshold": self.same_session_retries,
            "full_replan_threshold": self.max_cycles,
            "retry_delay": self.stage_retry_delay,
            "retry_wait": self.api_retry_wait,
            "retry_max_wait": self.api_retry_max_wait,
            "max_attempts": self.same_session_retries,
        })
        return argparse.Namespace(**values)


def is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
