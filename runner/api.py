"""Canonical public entry point for CLI, UIs, skills, and Python callers."""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from .bootstrap import execute
from .config import EventHandler, RuntimeConfig
from .config.defaults import (
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
from .errors import ConfigurationError, RunnerError, is_transient_error
from .extensions import discover_extensions
from .plugins.registry import (
    merge_plugin_config,
    plugin_config_from_namespace,
    plugin_config_from_request,
)
from .utils import append_bounded_log
from .version import __version__
from .workflow.loader import load_default_workflow, load_workflow
from .workflow.snapshot import load_snapshot


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
    workflow_file: str | None = None
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
    api_wait_timeout: float = DEFAULT_API_WAIT_TIMEOUT
    watchdog_interval: float = DEFAULT_WATCHDOG_INTERVAL
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    review_retries: int = DEFAULT_REVIEW_RETRIES
    max_cycles: int = DEFAULT_MAX_CYCLES
    retry_delay: float = 2
    retry_wait: float = 5
    retry_max_wait: float = 300
    final_ai_validations: int = DEFAULT_FINAL_AI_VALIDATIONS
    final_ai_required_passes: int = DEFAULT_FINAL_AI_REQUIRED_PASSES
    loop_context_compress: bool = DEFAULT_LOOP_CONTEXT_COMPRESS
    loop_context_compress_threshold: float = DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD
    plugins: dict[str, dict[str, Any]] = field(default_factory=dict)
    work_dir: str = ".ai-task-runner"
    resume: bool = False
    force_new: bool = False
    plan_only: bool = False
    human_output: bool = False
    json_events: bool = False

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> RunRequest:
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
            workflow_file=getattr(args, "workflow", None),
            backend=args.backend,
            command=args.command,
            sandbox=getattr(args, "sandbox", False),
            agent_args=list(args.agent_arg),
            validator_args=list(args.validator_arg),
            protect_files=list(args.protect_file),
            validator_timeout=args.validator_timeout,
            agent_timeout=args.agent_timeout,
            planning_timeout=args.planning_timeout,
            agent_idle_after_change_timeout=args.agent_idle_after_change_timeout,
            api_wait_timeout=getattr(args, "api_wait_timeout", DEFAULT_API_WAIT_TIMEOUT),
            watchdog_interval=getattr(args, "watchdog_interval", DEFAULT_WATCHDOG_INTERVAL),
            max_attempts=args.max_attempts,
            review_retries=getattr(args, "review_retries", DEFAULT_REVIEW_RETRIES),
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
            plugins=plugin_config_from_namespace(args),
            work_dir=args.work_dir,
            resume=args.resume,
            force_new=args.force_new,
            plan_only=args.plan_only,
            human_output=not args.json_events,
            json_events=args.json_events,
        )

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> RunRequest:
        """Build a request from JSON-like data while rejecting unknown keys."""
        allowed = {item.name for item in fields(cls)}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError("unknown request fields: " + ", ".join(unknown))
        return cls(**dict(values))

    def to_runtime_config(
        self,
        on_event: EventHandler | None = None,
    ) -> RuntimeConfig:
        """Resolve public request inputs into the typed execution contract."""
        discover_extensions()
        ai_validator_prompt = self._effective_ai_validator_prompt()
        frozen = (
            load_snapshot(self.project_root, self.work_dir)
            if self.resume and not self.script and not self.force_new
            else None
        )
        workflow = frozen or (
            load_workflow(self.workflow_file)
            if self.workflow_file
            else load_default_workflow(self.validator, ai_validator_prompt)
        )
        return RuntimeConfig(
            goal=self._effective_goal(),
            goal_file=self.goal_file,
            project_root=self.project_root,
            script=self.script,
            validator=self.validator,
            validator_prompt=self.validator_prompt,
            ai_validator_prompt=ai_validator_prompt,
            ai_validator_prompt_file=self.ai_validator_prompt_file,
            workflow=workflow,
            workflow_explicit=bool(self.workflow_file),
            backend=self.backend,
            command=self.command,
            sandbox=self.sandbox,
            agent_args=self.agent_args,
            validator_args=self.validator_args,
            protect_files=self.protect_files,
            validator_timeout=self.validator_timeout,
            agent_timeout=self.agent_timeout,
            planning_timeout=self.planning_timeout,
            agent_idle_after_change_timeout=self.agent_idle_after_change_timeout,
            api_retry_timeout=self.api_wait_timeout,
            watchdog_interval=self.watchdog_interval,
            same_session_retries=self.max_attempts,
            review_retries=self.review_retries,
            max_cycles=self.max_cycles,
            stage_retry_delay=self.retry_delay,
            api_retry_wait=self.retry_wait,
            api_retry_max_wait=self.retry_max_wait,
            final_ai_validations=self.final_ai_validations,
            final_ai_required_passes=self.final_ai_required_passes,
            plugins=merge_plugin_config(plugin_config_from_request(self), self.plugins),
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
        self.normalized_config()

    def normalized_config(
        self,
        on_event: EventHandler | None = None,
    ) -> RuntimeConfig:
        """Resolve public inputs and return the validated execution contract."""
        self._validate_request_source()
        if self.ai_validator_prompt and self.ai_validator_prompt_file:
            raise ValueError("use either ai_validator_prompt or ai_validator_prompt_file, not both")
        for name in ("validator_prompt", "ai_validator_prompt"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")  # noqa: TRY004
        config = self.to_runtime_config(on_event)
        config.validate()
        return config

    def _validate_request_source(self) -> None:
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


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    state_files: tuple[str, ...]
    states: tuple[dict[str, Any], ...]

    @property
    def completed(self) -> bool:
        return self.exit_code == 0 and bool(self.states) and all(
            state.get("completed") is True and state.get("stage") == "completed"
            for state in self.states
        )


def run(
    request: RunRequest | Mapping[str, Any],
    on_event: EventHandler | None = None,
) -> RunResult:
    """Run until Final Validator PASS (or plan-only), sharing recovery across all callers."""
    if not isinstance(request, RunRequest):
        request = RunRequest.from_mapping(request)

    config = request.normalized_config(on_event)
    while True:
        try:
            exit_code = execute(config)
            result = _result(request, exit_code)
            if request.plan_only or result.completed:
                return result
            config = _resume_config(request, config, result.state_files)
            _report_retry(
                request,
                on_event,
                "run returned before Final Validator completion; resuming saved state",
            )
        except KeyboardInterrupt:
            raise
        except ConfigurationError:
            raise
        except RunnerError as error:
            config = _resume_config(request, config)
            kind = "service wait window exhausted" if is_transient_error(error) else "runner failure"
            _report_retry(request, on_event, f"{kind}: {error}")
        except Exception as error:
            _log_unexpected(request, error)
            config = _resume_config(request, config)
            _report_retry(
                request, on_event, f"{type(error).__name__}: {error}; retrying"
            )
        if config.stage_retry_delay:
            time.sleep(config.stage_retry_delay)


def _result(request: RunRequest, exit_code: int) -> RunResult:
    state_files = _state_files(request)
    states = tuple(_read_state(path) for path in state_files if path.is_file())
    return RunResult(
        exit_code=exit_code,
        state_files=tuple(str(path) for path in state_files),
        states=states,
    )


def _resume_config(
    request: RunRequest,
    config: RuntimeConfig,
    state_files: tuple[str, ...] | list[str] | None = None,
) -> RuntimeConfig:
    paths = (
        [Path(path) for path in state_files]
        if state_files is not None
        else _state_files(request)
    )
    return replace(
        config,
        resume=any(path.is_file() for path in paths),
        force_new=False,
    )


def _log_unexpected(request: RunRequest, error: BaseException) -> None:
    log = Path(request.project_root, request.work_dir, "exception.log").resolve()
    append_bounded_log(
        log,
        f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{type(error).__name__}: {error}\n{traceback.format_exc()}",
    )


def _report_retry(
    request: RunRequest,
    callback: EventHandler | None,
    message: str,
) -> None:
    event = {
        "schema_version": 1,
        "runner_version": __version__,
        "type": "runner.retry",
        "action": "retry",
        "timestamp": time.time(),
        "message": message,
    }
    if callback is not None:
        try:
            callback(event)
        except Exception:
            pass
    if request.json_events:
        try:
            print(json.dumps(event), flush=True)
        except (BrokenPipeError, OSError):
            pass
    elif request.human_output:
        print(f"ERROR: {message}", file=sys.stderr)


def state_files(request: RunRequest | Mapping[str, Any]) -> tuple[str, ...]:
    """Return durable state locations without loading Workflow or runtime plugins."""
    if not isinstance(request, RunRequest):
        request = RunRequest.from_mapping(request)
    return tuple(str(path) for path in _state_files(request))


def _state_files(request: RunRequest) -> list[Path]:
    root = Path(request.project_root).resolve()
    if not request.script:
        return [root / request.work_dir / "state.json"]

    script = Path(request.script).expanduser().resolve()
    try:
        import yaml
        data = yaml.safe_load(script.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    result: list[Path] = []
    for index, item in enumerate(data, 1):
        child_root = root
        if isinstance(item, dict) and isinstance(item.get("project_root"), str):
            value = Path(item["project_root"]).expanduser()
            child_root = (value if value.is_absolute() else root / value).resolve()
        child_work = Path(request.work_dir) / "script" / f"{index:03d}"
        result.append(child_root / child_work / "state.json")
    return result


def _read_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "EventHandler",
    "RunRequest",
    "RunResult",
    "__version__",
    "run",
    "state_files",
]
