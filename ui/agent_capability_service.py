"""Cached projection of native Agent capabilities for the Project Chat UI."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from tool.agent_catalog import capability_catalog


class AgentCapabilityService:
    def __init__(self, repo_root: Path, *, ttl_seconds: float = 30) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._lock = threading.RLock()
        self._cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    def get(
        self,
        project: Path,
        backend: str,
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        agent = str(backend or "").strip()
        if not agent:
            raise ValueError("Agent is required for capability discovery")
        key = (str(project.resolve()), agent)
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if (
                not refresh
                and cached is not None
                and now - cached[0] < self.ttl_seconds
            ):
                return {**cached[1], "cached": True}

        payload = self._discover(project, agent)
        with self._lock:
            self._cache[key] = (time.monotonic(), payload)
        return {**payload, "cached": False}

    def invalidate(self, project: Path | None = None, backend: str = "") -> None:
        project_key = str(project.resolve()) if project is not None else ""
        agent = str(backend or "").strip()
        with self._lock:
            for key in list(self._cache):
                if project_key and key[0] != project_key:
                    continue
                if agent and key[1] != agent:
                    continue
                del self._cache[key]

    def _discover(self, project: Path, backend: str) -> dict[str, Any]:
        try:
            payload = capability_catalog(project, backend)
        except Exception as exc:
            raise ValueError(f"Agent capability discovery failed: {exc}") from exc

        values = payload.get("capabilities")
        if not isinstance(values, list):
            raise ValueError("Agent capability discovery is missing capabilities")

        capabilities: list[dict[str, Any]] = []
        for item in values:
            if not isinstance(item, dict):
                raise ValueError("Agent capability discovery returned invalid capability")
            token = str(item.get("token") or "").strip()
            name = str(item.get("name") or "").strip()
            kind = str(item.get("kind") or "").strip()
            if not token.startswith("/") or not name or kind not in {"command", "skill"}:
                raise ValueError("Agent capability discovery returned invalid capability")
            capabilities.append({
                "token": token,
                "name": name,
                "description": str(item.get("description") or ""),
                "kind": kind,
                "source": str(item.get("source") or backend),
                "user_invocable": bool(item.get("user_invocable")),
                "enabled": bool(item.get("enabled")),
                "permission": str(item.get("permission") or ""),
                "availability": str(item.get("availability") or ""),
            })
        return {"agent": backend, "capabilities": capabilities}
