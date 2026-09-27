"""Compatibility metadata for workflow execution modes.

The production runtime is intentionally single-runner. The public execution_mode
field remains for backward-compatible request/state identity, while future
behavioral variation belongs behind FlowEngine as RoutingStrategy.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionModeSpec:
    name: str
    requires_workflow: bool = True
    description: str = ""


_MODES: dict[str, ExecutionModeSpec] = {
    "linear": ExecutionModeSpec(
        name="linear",
        requires_workflow=True,
        description="Linear Workflow with rollback/recovery/loop routing.",
    ),
}


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


__all__ = [
    "ExecutionModeSpec",
    "execution_mode_catalog",
    "execution_mode_names",
    "execution_mode_spec",
]
