"""Shared in-process Agent catalog projection for UI and CLI helpers."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from runner.agent import (
    BackendError,
    available_models,
    chat_features,
    discover_capabilities,
    interaction_modes,
    reasoning_options,
)
from runner.plugins.registry import discover_plugins


def capability_catalog(project: Path, backend: str) -> dict[str, Any]:
    agent = str(backend or "").strip()
    if not agent:
        raise ValueError("Agent is required for capability discovery")
    discover_plugins()
    values = discover_capabilities(agent, Path(project).expanduser().resolve())
    return {
        "backend": agent,
        "capabilities": [asdict(item) for item in values],
    }


def settings_catalog(
    project: Path,
    backend: str,
    model: str = "",
) -> dict[str, Any]:
    agent = str(backend or "").strip()
    if not agent:
        raise ValueError("Agent is required")
    root = Path(project).expanduser().resolve()
    discover_plugins()
    models = available_models(agent, root)
    try:
        modes = interaction_modes(agent)
    except BackendError:
        modes = ()
    reasoning = reasoning_options(agent, root, str(model or "").strip())
    features = chat_features(agent, root)
    return {
        "agent": agent,
        "models": models,
        "modes": [asdict(item) for item in modes],
        "reasoning": [asdict(item) for item in reasoning],
        "features": asdict(features),
    }


__all__ = ["capability_catalog", "settings_catalog"]
