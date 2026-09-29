"""Canonical public entry point for CLI, UI and Python callers."""
from __future__ import annotations

import argparse
import json
import time
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from .bootstrap import execute
from .config.defaults import (
    DEFAULT_AGENT_IDLE_AFTER_CHANGE_TIMEOUT,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_BACKEND,
    DEFAULT_FINAL_AI_REQUIRED_PASSES,
    DEFAULT_FINAL_AI_VALIDATIONS,
    DEFAULT_PLANNING_TIMEOUT,
    DEFAULT_STAGE_RETRIES,
    DEFAULT_VALIDATOR_TIMEOUT,
    DEFAULT_WATCHDOG_INTERVAL,
    DEFAULT_WORKER_HANG_TIMEOUT,
)
from .config.runtime import EventHandler, RuntimeConfig
from .errors import ConfigurationError, RunnerError, is_transient_error
from .plugins.registry import (
    discover_plugins,
    merge_plugin_config,
    plugin_config_from_namespace,
    plugin_config_from_request,
)
from .runtime.events import retry_event
from .runtime.events import sleep_with_heartbeat
from .utils import append_bounded_log
from .version import __version__
from .workflow.loader import load_default_workflow, load_workflow
from .resources import load_run_resource, load_snapshot


@dataclass
class RunRequest:
    goal: str | None = None
    goal_file: str | None = None
    project_root: str = "."
    project_name: str = ""
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
    watchdog_interval: float = DEFAULT_WATCHDOG_INTERVAL
    worker_hang_timeout: float = DEFAULT_WORKER_HANG_TIMEOUT
    stage_retries: int = DEFAULT_STAGE_RETRIES
    retry_delay: float = 5
    retry_max_delay: float = 300

    final_ai_validations: int = DEFAULT_FINAL_AI_VALIDATIONS
    final_ai_required_passes: int = DEFAULT_FINAL_AI_REQUIRED_PASSES
    ai_validator_yolo: bool = False
    readonly_safety: str = "restore"
    plugins: dict[str, dict[str, Any]] = field(default_factory=dict)

    work_dir: str = ".ai-task-runner"
    resume: bool = False
    force_new: bool = False
    human_output: bool = False
    json_events: bool = False
    auto_register_ui_project: bool = False

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "RunRequest":
        return cls(
            goal=args.goal,
            goal_file=args.goal_file,
            project_root=args.project_root,
            project_name=getattr(args, "project_name", ""),
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
            watchdog_interval=args.watchdog_interval,
            worker_hang_timeout=args.worker_hang_timeout,
            stage_retries=args.stage_retries,
            retry_delay=args.retry_delay,
            retry_max_delay=args.retry_max_delay,
            final_ai_validations=args.final_ai_validations,
            final_ai_required_passes=args.final_ai_required_passes,
            ai_validator_yolo=args.ai_validator_yolo,
            readonly_safety=args.readonly_safety,
            plugins=plugin_config_from_namespace(args),
            work_dir=args.work_dir,
            resume=args.resume,
            force_new=args.force_new,
            human_output=not args.json_events,
            json_events=args.json_events,
            auto_register_ui_project=getattr(args, "auto_register_ui_project", True),
        )

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "RunRequest":
        allowed = {item.name for item in fields(cls)}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError("unknown request fields: " + ", ".join(unknown))
        return cls(**dict(values))

    def normalized_config(
        self,
        on_event: EventHandler | None = None,
    ) -> RuntimeConfig:
        self._validate_source()
        if self.ai_validator_prompt and self.ai_validator_prompt_file:
            raise ValueError(
                "use either ai_validator_prompt or ai_validator_prompt_file, not both"
            )

        discover_plugins()
        frozen_run = self.resume and not self.script and not self.force_new
        frozen_goal = (
            load_run_resource(self.project_root, self.work_dir, "goal")
            if frozen_run
            else None
        )
        frozen_ai = (
            load_run_resource(self.project_root, self.work_dir, "ai_validator_prompt")
            if frozen_run
            else None
        )

        goal = frozen_goal[1] if frozen_goal else self._effective_goal()
        goal_file = frozen_goal[0] if frozen_goal else self.goal_file
        ai_prompt = frozen_ai[1] if frozen_ai else self._effective_ai_validator_prompt()
        ai_prompt_file = frozen_ai[0] if frozen_ai else self.ai_validator_prompt_file
        frozen_workflow = (
            load_snapshot(self.project_root, self.work_dir)
            if frozen_run
            else None
        )
        workflow = frozen_workflow or (
            load_workflow(self.workflow_file)
            if self.workflow_file
            else load_default_workflow(self.validator, ai_prompt)
        )

        config = RuntimeConfig(
            goal=goal,
            goal_file=goal_file,
            project_root=self.project_root,
            project_name=self.project_name,
            script=self.script,
            validator=self.validator,
            validator_prompt=self.validator_prompt,
            ai_validator_prompt=ai_prompt,
            ai_validator_prompt_file=ai_prompt_file,
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
            watchdog_interval=self.watchdog_interval,
            worker_hang_timeout=self.worker_hang_timeout,
            stage_retries=self.stage_retries,
            retry_delay=self.retry_delay,
            retry_max_delay=self.retry_max_delay,
            final_ai_validations=self.final_ai_validations,
            final_ai_required_passes=self.final_ai_required_passes,
            ai_validator_yolo=self.ai_validator_yolo,
            readonly_safety=self.readonly_safety,
            plugins=merge_plugin_config(plugin_config_from_request(self), self.plugins),
            work_dir=self.work_dir,
            resume=self.resume,
            force_new=self.force_new,
            json_events=self.json_events,
            human_output=self.human_output,
            auto_register_ui_project=self.auto_register_ui_project,
            event_callback=on_event,
        )
        config.validate()
        return config

    def validate(self) -> None:
        self.normalized_config()

    def _validate_source(self) -> None:
        if not isinstance(self.project_root, str) or not self.project_root.strip():
            raise ValueError("project_root must be a non-empty string")
        if not isinstance(self.project_name, str):
            raise ValueError("project_name must be a string")
        if self.goal and self.goal_file:
            raise ValueError("use either goal or goal_file, not both")
        if self.script and (self.goal or self.goal_file):
            raise ValueError("use either goal/goal_file or script, not both")
        if not self.script and not self.resume and not self._effective_goal().strip():
            raise ValueError("goal or goal_file is required unless script or resume is used")
        if (
            not self.script
            and not self.workflow_file
            and not isinstance(self.validator, str)
        ):
            raise ValueError("validator is required unless script or workflow_file is used")

    def _effective_goal(self) -> str:
        if isinstance(self.goal, str):
            return self.goal
        return _read_text_file(self.goal_file, "goal_file") if self.goal_file else ""

    def _effective_ai_validator_prompt(self) -> str:
        if self.ai_validator_prompt:
            return self.ai_validator_prompt
        return (
            _read_text_file(self.ai_validator_prompt_file, "ai_validator_prompt_file")
            if self.ai_validator_prompt_file
            else ""
        )


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    state_files: tuple[str, ...]
    states: tuple[dict[str, Any], ...]

    @property
    def completed(self) -> bool:
        return (
            self.exit_code == 0
            and bool(self.states)
            and all(
                state.get("completed") is True and state.get("stage") == "completed"
                for state in self.states
            )
        )


def run(
    request: RunRequest | Mapping[str, Any],
    on_event: EventHandler | None = None,
) -> RunResult:
    """Run until the Workflow completes or fails closed."""
    if not isinstance(request, RunRequest):
        request = RunRequest.from_mapping(request)

    config = request.normalized_config(on_event)
    unexpected_key: tuple[type[BaseException], str] | None = None
    unexpected_repeats = 0
    incomplete_key = ""
    incomplete_repeats = 0

    while True:
        try:
            result = _result(request, execute(config))
            unexpected_key = None
            unexpected_repeats = 0
            if result.completed or result.exit_code != 0:
                return result

            progress_key = _incomplete_progress_key(result)
            incomplete_repeats = (
                incomplete_repeats + 1 if progress_key == incomplete_key else 1
            )
            incomplete_key = progress_key
            if incomplete_repeats >= 3:
                raise RunnerError("run returned repeatedly without Workflow progress")

            config = _resume_config(request, config, result.state_files)
            _report_retry(
                request,
                on_event,
                "run returned before Workflow completion; resuming saved state",
            )
        except KeyboardInterrupt:
            raise
        except ConfigurationError:
            raise
        except RunnerError as error:
            if not is_transient_error(error):
                raise
            config = _resume_config(request, config)
            _report_retry(request, on_event, f"service wait window exhausted: {error}")
        except Exception as error:
            _log_unexpected(request, error)
            key = _unexpected_error_key(error)
            unexpected_repeats = unexpected_repeats + 1 if key == unexpected_key else 1
            unexpected_key = key
            if unexpected_repeats >= 3:
                raise
            config = _resume_config(request, config)
            _report_retry(
                request,
                on_event,
                f"{type(error).__name__}: {error}; retrying "
                f"({unexpected_repeats}/2 automatic recoveries)",
            )

        if config.retry_delay:
            sleep_with_heartbeat(config.retry_delay)


def state_files(request: RunRequest | Mapping[str, Any]) -> tuple[str, ...]:
    if not isinstance(request, RunRequest):
        request = RunRequest.from_mapping(request)
    return tuple(str(path) for path in _state_files(request))


def _result(request: RunRequest, exit_code: int) -> RunResult:
    paths = _state_files(request)
    states = tuple(_read_state(path) for path in paths if path.is_file())
    return RunResult(
        exit_code=exit_code,
        state_files=tuple(str(path) for path in paths),
        states=states,
    )


def _resume_config(
    request: RunRequest,
    config: RuntimeConfig,
    state_paths: tuple[str, ...] | list[str] | None = None,
) -> RuntimeConfig:
    paths = (
        [Path(path) for path in state_paths]
        if state_paths is not None
        else _state_files(request)
    )
    return replace(
        config,
        resume=any(path.is_file() for path in paths),
        force_new=False,
    )


def _incomplete_progress_key(result: RunResult) -> str:
    summary = []
    for state in result.states:
        tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
        summary.append({
            "run_id": state.get("run_id"),
            "stage": state.get("stage"),
            "current": state.get("current"),
            "cycle": state.get("cycle"),
            "workflow_position": state.get("workflow_position"),
            "task_step": state.get("task_step"),
            "completed": state.get("completed"),
            "tasks": [
                {
                    "id": task.get("id"),
                    "status": task.get("status"),
                    "attempts": task.get("attempts"),
                }
                for task in tasks
                if isinstance(task, dict)
            ],
        })
    return json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _state_files(request: RunRequest) -> list[Path]:
    root = Path(request.project_root).resolve()
    if not request.script:
        return [root / request.work_dir / "state.json"]

    try:
        import yaml
        data = yaml.safe_load(Path(request.script).expanduser().resolve().read_text())
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
        result.append(
            child_root
            / Path(request.work_dir)
            / "script"
            / f"{index:03d}"
            / "state.json"
        )
    return result


def _read_text_file(filename: str, field_name: str) -> str:
    path = Path(filename).expanduser()
    if not path.is_file():
        raise ValueError(f"{field_name} not found: {filename}")
    return path.read_text(encoding="utf-8-sig")


def _read_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _unexpected_error_key(error: BaseException) -> tuple[type[BaseException], str]:
    frames = traceback.extract_tb(error.__traceback__) if error.__traceback__ else []
    location = (
        f"{frames[-1].filename}:{frames[-1].lineno}:{frames[-1].name}"
        if frames
        else str(error)
    )
    return type(error), location


def _log_unexpected(request: RunRequest, error: BaseException) -> None:
    append_bounded_log(
        Path(request.project_root, request.work_dir, "exception.log").resolve(),
        f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{type(error).__name__}: {error}\n{traceback.format_exc()}",
    )


def _report_retry(
    request: RunRequest,
    callback: EventHandler | None,
    message: str,
) -> None:
    event = retry_event(message)
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
        print(f"ERROR: {message}")


__all__ = [
    "EventHandler",
    "RunRequest",
    "RunResult",
    "__version__",
    "run",
    "state_files",
]
