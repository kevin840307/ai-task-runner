"""Validated runtime configuration shared by runner stages."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Any, Callable

from .defaults import (
    DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_BACKEND,
    DEFAULT_FINAL_AI_REQUIRED_PASSES,
    DEFAULT_FINAL_AI_VALIDATIONS,
    DEFAULT_LOOP_CONTEXT_COMPRESS,
    DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_CYCLES,
    DEFAULT_PLANNING_TIMEOUT,
    DEFAULT_VALIDATOR_TIMEOUT,
)

EventHandler = Callable[[dict[str, Any]], None]


@dataclass
class RuntimeConfig:
    """Resolved internal settings; unlike RunRequest, file inputs are loaded."""

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
    agent_arg: list[str] = field(default_factory=list)
    validator_arg: list[str] = field(default_factory=list)
    protect_file: list[str] = field(default_factory=list)
    validator_timeout: int = DEFAULT_VALIDATOR_TIMEOUT
    agent_timeout: int = DEFAULT_AGENT_TIMEOUT
    planning_timeout: int = DEFAULT_PLANNING_TIMEOUT
    agent_idle_after_change_timeout: float = DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    max_cycles: int = DEFAULT_MAX_CYCLES
    retry_delay: float = 2
    retry_wait: float = 5
    retry_max_wait: float = 300
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
    def from_namespace(cls, args: argparse.Namespace) -> "RuntimeConfig":
        """Adapt legacy internal Namespace callers without weakening defaults."""
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
            agent_arg=list(getattr(args, "agent_arg", [])),
            validator_arg=list(getattr(args, "validator_arg", [])),
            protect_file=list(getattr(args, "protect_file", [])),
            validator_timeout=getattr(args, "validator_timeout", DEFAULT_VALIDATOR_TIMEOUT),
            agent_timeout=getattr(args, "agent_timeout", DEFAULT_AGENT_TIMEOUT),
            planning_timeout=getattr(args, "planning_timeout", DEFAULT_PLANNING_TIMEOUT),
            agent_idle_after_change_timeout=getattr(
                args,
                "agent_idle_after_change_timeout",
                DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
            ),
            max_attempts=getattr(args, "max_attempts", DEFAULT_MAX_ATTEMPTS),
            max_cycles=getattr(args, "max_cycles", DEFAULT_MAX_CYCLES),
            retry_delay=getattr(args, "retry_delay", 2),
            retry_wait=getattr(args, "retry_wait", 5),
            retry_max_wait=getattr(args, "retry_max_wait", 300),
            final_ai_validations=getattr(
                args, "final_ai_validations", DEFAULT_FINAL_AI_VALIDATIONS
            ),
            final_ai_required_passes=getattr(
                args,
                "final_ai_required_passes",
                DEFAULT_FINAL_AI_REQUIRED_PASSES,
            ),
            loop_context_compress=getattr(
                args, "loop_context_compress", DEFAULT_LOOP_CONTEXT_COMPRESS
            ),
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
        """Compatibility adapter for integrations expecting argparse fields."""
        return argparse.Namespace(**vars(self))
