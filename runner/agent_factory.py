"""Consistent construction and stage configuration for agent clients."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .agent import AgentClient
from .backends import AgentMode, configure_agent_args
from .config import RuntimeConfig
from .defaults import DEFAULT_AGENT_TIMEOUT, DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD

AgentConstructor = Callable[..., AgentClient]


@dataclass(frozen=True)
class AgentFactory:
    config: RuntimeConfig
    root: Path
    debug_dir: Path | None
    constructor: AgentConstructor = AgentClient

    def arguments(
        self,
        mode: AgentMode,
        *,
        allow_project_read: bool = False,
    ) -> list[str]:
        return configure_agent_args(
            self.config.backend,
            mode,
            getattr(self.config, "agent_arg", []),
            allow_project_read=allow_project_read,
        )

    def create(
        self,
        mode: AgentMode,
        *,
        session_id: str = "",
        timeout: int | None = None,
        allow_project_read: bool = False,
        extra_args: Sequence[str] | None = None,
    ) -> AgentClient:
        return self.constructor(
            backend=self.config.backend,
            command=self.config.command,
            root=self.root,
            extra_args=(
                list(extra_args)
                if extra_args is not None
                else self.arguments(
                    mode,
                    allow_project_read=allow_project_read,
                )
            ),
            session_id=session_id,
            timeout=(
                getattr(self.config, "agent_timeout", DEFAULT_AGENT_TIMEOUT)
                if timeout is None
                else timeout
            ),
            debug_dir=self.debug_dir,
            loop_context_compress=getattr(
                self.config, "loop_context_compress", False
            ),
            loop_context_compress_threshold=(
                getattr(
                    self.config,
                    "loop_context_compress_threshold",
                    DEFAULT_LOOP_CONTEXT_COMPRESS_THRESHOLD,
                )
            ),
        )

    def configure(
        self,
        agent: AgentClient,
        mode: AgentMode,
        *,
        allow_project_read: bool = False,
    ) -> None:
        agent.set_extra_args(
            self.arguments(mode, allow_project_read=allow_project_read)
        )
