"""Top-level orchestration mode registry.

Execution modes own control-flow semantics. Shared Stage/backend/plugin/runtime
capabilities stay below this boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .config.runtime import RuntimeConfig

ExecutionRunner = Callable[["RuntimeConfig"], int]


@dataclass(frozen=True)
class ExecutionModeSpec:
    name: str
    runner: ExecutionRunner
    requires_workflow: bool = True
    description: str = ""


_MODES: dict[str, ExecutionModeSpec] = {}


def register_execution_mode(
    name: str,
    runner: ExecutionRunner,
    *,
    requires_workflow: bool = True,
    description: str = "",
    replace: bool = False,
) -> None:
    key = str(name or "").strip()
    if not key:
        raise ValueError("execution mode name is required")
    if not callable(runner):
        raise TypeError("execution mode runner must be callable")
    if key in _MODES and not replace:
        raise ValueError(f"execution mode already registered: {key}")
    _MODES[key] = ExecutionModeSpec(
        name=key,
        runner=runner,
        requires_workflow=bool(requires_workflow),
        description=str(description or "").strip(),
    )


def execution_mode_names() -> tuple[str, ...]:
    return tuple(sorted(_MODES))


def execution_mode_spec(name: str) -> ExecutionModeSpec:
    key = str(name or "").strip()
    try:
        return _MODES[key]
    except KeyError as exc:
        supported = ", ".join(execution_mode_names()) or "(none)"
        raise ValueError(
            f"unsupported execution_mode: {key or '<empty>'}; supported: {supported}"
        ) from exc


def execution_mode_catalog() -> dict[str, dict[str, object]]:
    return {
        name: {
            "name": spec.name,
            "requires_workflow": spec.requires_workflow,
            "description": spec.description,
        }
        for name, spec in sorted(_MODES.items())
    }


def execute_execution_mode(config: "RuntimeConfig") -> int:
    return execution_mode_spec(config.execution_mode).runner(config)


def _run_linear(config: "RuntimeConfig") -> int:
    from .task_runner import TaskRunner

    return TaskRunner(config).run()


register_execution_mode(
    "linear",
    _run_linear,
    requires_workflow=True,
    description="Linear Workflow with rollback/recovery/loop routing.",
)


__all__ = [
    "ExecutionModeSpec",
    "execute_execution_mode",
    "execution_mode_catalog",
    "execution_mode_names",
    "execution_mode_spec",
    "register_execution_mode",
]
