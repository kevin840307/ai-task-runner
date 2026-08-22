"""Canonical public entry point for CLI, UIs, skills, and Python callers."""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

from .backends import backend_names
from .config import EventHandler, RuntimeConfig
from .defaults import (
    DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_BACKEND,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_CYCLES,
    DEFAULT_PLANNING_TIMEOUT,
    DEFAULT_FINAL_AI_VALIDATIONS,
    DEFAULT_FINAL_AI_REQUIRED_PASSES,
    DEFAULT_VALIDATOR_TIMEOUT,
    DEFAULT_LOOP_CONTEXT_COMPRESS,
    DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD,
)
from .core import execute
from .version import __version__


@dataclass
class RunRequest:
    """Serializable request shared by every integration surface."""

    goal: str | None = None
    goal_file: str | None = None
    project_root: str = "."
    script: str | None = None
    validator: str | None = None
    validator_prompt: str = ""
    ai_validator_prompt: str = ""
    ai_validator_prompt_file: str | None = None
    backend: str = DEFAULT_BACKEND
    command: str | None = None
    agent_args: list[str] = field(default_factory=list)
    validator_args: list[str] = field(default_factory=list)
    protect_files: list[str] = field(default_factory=list)
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
    human_output: bool = False
    json_events: bool = False

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "RunRequest":
        """Convert CLI arguments into the canonical request model."""
        return cls(
            goal=args.goal,
            goal_file=args.goal_file,
            project_root=args.project_root,
            script=args.script,
            validator=args.validator,
            validator_prompt=args.validator_prompt,
            ai_validator_prompt=getattr(args, "ai_validator_prompt", ""),
            ai_validator_prompt_file=getattr(args, "ai_validator_prompt_file", None),
            backend=args.backend,
            command=args.command,
            agent_args=list(args.agent_arg),
            validator_args=list(args.validator_arg),
            protect_files=list(args.protect_file),
            validator_timeout=args.validator_timeout,
            agent_timeout=args.agent_timeout,
            planning_timeout=args.planning_timeout,
            agent_idle_after_change_timeout=args.agent_idle_after_change_timeout,
            max_attempts=args.max_attempts,
            max_cycles=args.max_cycles,
            retry_delay=args.retry_delay,
            retry_wait=args.retry_wait,
            retry_max_wait=args.retry_max_wait,
            final_ai_validations=getattr(
                args, "final_ai_validations", DEFAULT_FINAL_AI_VALIDATIONS
            ),
            final_ai_required_passes=getattr(
                args, "final_ai_required_passes", DEFAULT_FINAL_AI_REQUIRED_PASSES
            ),
            loop_context_compress=getattr(args, "loop_context_compress", False),
            loop_context_compress_threshold=getattr(
                args, "loop_context_compress_threshold", DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD
            ),
            work_dir=args.work_dir,
            resume=args.resume,
            force_new=args.force_new,
            plan_only=args.plan_only,
            human_output=not args.json_events,
            json_events=args.json_events,
        )

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "RunRequest":
        """Build a request from JSON-like data while rejecting unknown keys."""
        allowed = {item.name for item in fields(cls)}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError("unknown request fields: " + ", ".join(unknown))
        return cls(**dict(values))

    def to_namespace(
        self,
        on_event: EventHandler | None = None,
    ) -> argparse.Namespace:
        """Compatibility adapter for integrations expecting argparse fields."""
        return self.to_runtime_config(on_event).to_namespace()

    def to_runtime_config(
        self,
        on_event: EventHandler | None = None,
    ) -> RuntimeConfig:
        """Resolve public request inputs into the typed execution contract."""
        return RuntimeConfig(
            goal=self._effective_goal(),
            goal_file=self.goal_file,
            project_root=self.project_root,
            script=self.script,
            validator=self.validator,
            validator_prompt=self.validator_prompt,
            ai_validator_prompt=self._effective_ai_validator_prompt(),
            ai_validator_prompt_file=self.ai_validator_prompt_file,
            backend=self.backend,
            command=self.command,
            agent_arg=list(self.agent_args),
            validator_arg=list(self.validator_args),
            protect_file=list(self.protect_files),
            validator_timeout=self.validator_timeout,
            agent_timeout=self.agent_timeout,
            planning_timeout=self.planning_timeout,
            agent_idle_after_change_timeout=self.agent_idle_after_change_timeout,
            max_attempts=self.max_attempts,
            max_cycles=self.max_cycles,
            retry_delay=self.retry_delay,
            retry_wait=self.retry_wait,
            retry_max_wait=self.retry_max_wait,
            final_ai_validations=self.final_ai_validations,
            final_ai_required_passes=self.final_ai_required_passes,
            loop_context_compress=self.loop_context_compress,
            loop_context_compress_threshold=self.loop_context_compress_threshold,
            work_dir=self.work_dir,
            resume=self.resume,
            force_new=self.force_new,
            plan_only=self.plan_only,
            json_events=self.json_events,
            human_output=self.human_output,
            event_callback=on_event,
        )

    def validate(self) -> None:
        """Fail fast with clear errors for every integration surface."""
        if not isinstance(self.project_root, str) or not self.project_root.strip():
            raise ValueError("project_root must be a non-empty string")
        if self.goal and self.goal_file:
            raise ValueError("use either goal or goal_file, not both")
        if self.script and (self.goal or self.goal_file):
            raise ValueError("use either goal/goal_file or script, not both")
        if (
            not self.script
            and not self.resume
            and not self._effective_goal().strip()
        ):
            raise ValueError("goal or goal_file is required unless script or resume is used")
        if not self.script and not (
            isinstance(self.validator, str) and self.validator.strip()
        ):
            raise ValueError("validator is required unless script is used")
        if self.ai_validator_prompt and self.ai_validator_prompt_file:
            raise ValueError("use either ai_validator_prompt or ai_validator_prompt_file, not both")
        for name in ("validator_prompt", "ai_validator_prompt"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")
        if self.backend not in backend_names():
            raise ValueError(f"unsupported backend: {self.backend}")
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

        if not isinstance(self.validator_timeout, int) or self.validator_timeout <= 0:
            raise ValueError("validator_timeout must be a positive integer")
        if not isinstance(self.agent_timeout, int) or self.agent_timeout < 0:
            raise ValueError("agent_timeout must be a non-negative integer")
        if not isinstance(self.planning_timeout, int) or self.planning_timeout < 0:
            raise ValueError("planning_timeout must be a non-negative integer")
        if (
            not isinstance(self.agent_idle_after_change_timeout, (int, float))
            or self.agent_idle_after_change_timeout < 0
        ):
            raise ValueError(
                "agent_idle_after_change_timeout must be a non-negative number"
            )
        for name in ("max_attempts", "max_cycles"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.final_ai_validations, int) or self.final_ai_validations < 1:
            raise ValueError("final_ai_validations must be a positive integer")
        if (
            not isinstance(self.final_ai_required_passes, int)
            or not 0 <= self.final_ai_required_passes <= self.final_ai_validations
        ):
            raise ValueError(
                "final_ai_required_passes must be 0 or between 1 and final_ai_validations"
            )
        for name in ("retry_delay", "retry_wait", "retry_max_wait"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"{name} must be a non-negative number")
        if self.retry_max_wait < self.retry_wait:
            raise ValueError("retry_max_wait must be greater than or equal to retry_wait")
        if not isinstance(self.loop_context_compress, bool):
            raise ValueError("loop_context_compress must be a boolean")
        if (
            not isinstance(self.loop_context_compress_threshold, (int, float))
            or not 0 <= self.loop_context_compress_threshold <= 100
        ):
            raise ValueError("loop_context_compress_threshold must be between 0 and 100")

    def _effective_goal(self) -> str:
        if isinstance(self.goal, str):
            return self.goal
        if not self.goal_file:
            return ""
        return _read_text_file(self.goal_file, "goal_file")

    def _effective_ai_validator_prompt(self) -> str:
        if self.ai_validator_prompt:
            return self.ai_validator_prompt
        if not self.ai_validator_prompt_file:
            return ""
        return _read_text_file(
            self.ai_validator_prompt_file,
            "ai_validator_prompt_file",
        )


def _read_text_file(filename: str, field_name: str) -> str:
    path = Path(filename).expanduser()
    if not path.is_file():
        raise ValueError(f"{field_name} not found: {filename}")
    return path.read_text(encoding="utf-8-sig")


# Backward-compatible name used by the previous release.
RunConfig = RunRequest


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    state_files: tuple[str, ...]
    states: tuple[dict[str, Any], ...]

    @property
    def completed(self) -> bool:
        return self.exit_code == 0 and bool(self.states) and all(
            state.get("completed") is True for state in self.states
        )


def run(
    request: RunRequest | Mapping[str, Any],
    on_event: EventHandler | None = None,
) -> RunResult:
    """Execute one canonical request from any caller."""
    if not isinstance(request, RunRequest):
        request = RunRequest.from_mapping(request)

    request.validate()
    config = request.to_runtime_config(on_event)
    exit_code = execute(config)
    state_files = _state_files(request)
    states = tuple(_read_state(path) for path in state_files if path.is_file())
    return RunResult(
        exit_code=exit_code,
        state_files=tuple(str(path) for path in state_files),
        states=states,
    )


def _state_files(request: RunRequest) -> list[Path]:
    root = Path(request.project_root).resolve()
    work = root / request.work_dir
    if request.script:
        script_root = work / "script"
        return sorted(script_root.glob("*/state.json")) if script_root.exists() else []
    return [work / "state.json"]


def _read_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "__version__",
    "EventHandler",
    "RunConfig",
    "RunRequest",
    "RunResult",
    "run",
]
