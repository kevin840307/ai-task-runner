"""Versioned global product settings shared by UI/API/future orchestration CLI."""
from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
AUTO_WORKSPACE_POLICIES = {
    "busy-worktree",
    "always-main",
    "always-worktree",
}
APPEARANCES = {"system", "light", "dark"}
THEMES = {"teal", "blue", "violet", "amber", "rose"}
MOTIONS = {"full", "system", "reduced"}
LANGUAGES = {"zh-TW", "en"}
MODES = {"read", "auto", "yolo"}
REASONING_LEVELS = {"low", "medium", "high", "xhigh", "max"}


def default_global_settings() -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "execution": {
            "auto_workspace_policy": "busy-worktree",
            "merge_failure_limit": 3,
            "allow_concurrent_main_tasks": False,
        },
        "interface": {
            "appearance": "system",
            "theme": "teal",
            "motion": "full",
        },
        "language": "zh-TW",
        "defaults": {
            "agent": "",
            "model": "",
            "mode": "auto",
            "reasoning": "medium",
            "workflow": "",
        },
    }


class GlobalSettingsStore:
    """Single persistence/validation owner for app-global settings."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()

    def get(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return default_global_settings()
            return self._validate(self._read())

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("Global settings patch must be an object")
        unknown = set(patch) - {"version", "execution", "interface", "language", "defaults"}
        if unknown:
            raise ValueError(f"Unknown Global Settings field: {sorted(unknown)[0]}")
        with self._lock:
            current = self.get()
            merged = deepcopy(current)
            for section in ("execution", "interface", "defaults"):
                if section not in patch:
                    continue
                value = patch[section]
                if not isinstance(value, dict):
                    raise ValueError(f"Global Settings {section} must be an object")
                merged[section].update(value)
            if "language" in patch:
                merged["language"] = patch["language"]
            merged["version"] = SCHEMA_VERSION
            value = self._validate(merged)
            self._write(value)
            return value

    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Global Settings are invalid: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("Global Settings are invalid")
        return self._migrate(raw)

    @staticmethod
    def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
        version = raw.get("version")
        if version in (None, 0):
            # Pre-versioned drafts used the same logical section names. Treat
            # missing sections as defaults and validate the migrated result.
            migrated = default_global_settings()
            for section in ("execution", "interface", "defaults"):
                value = raw.get(section)
                if isinstance(value, dict):
                    migrated[section].update(value)
            if "language" in raw:
                migrated["language"] = raw["language"]
            return migrated
        if version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported Global Settings version: {version}")
        return raw

    @staticmethod
    def _text(value: Any, label: str, limit: int = 4096) -> str:
        text = str(value or "").strip()
        if len(text) > limit:
            raise ValueError(f"{label} is too long")
        return text

    @classmethod
    def _validate(cls, raw: dict[str, Any]) -> dict[str, Any]:
        value = default_global_settings()
        execution = raw.get("execution")
        interface = raw.get("interface")
        defaults = raw.get("defaults")
        if not isinstance(execution, dict):
            raise ValueError("Global Settings execution must be an object")
        if not isinstance(interface, dict):
            raise ValueError("Global Settings interface must be an object")
        if not isinstance(defaults, dict):
            raise ValueError("Global Settings defaults must be an object")

        policy = str(execution.get("auto_workspace_policy") or "").strip()
        if policy not in AUTO_WORKSPACE_POLICIES:
            raise ValueError("Invalid auto workspace policy")
        try:
            merge_limit = int(execution.get("merge_failure_limit"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Merge failure limit must be an integer") from exc
        if merge_limit < 0 or merge_limit > 100:
            raise ValueError("Merge failure limit must be between 0 and 100")
        concurrent = execution.get("allow_concurrent_main_tasks")
        if not isinstance(concurrent, bool):
            raise ValueError("Allow concurrent Main tasks must be boolean")
        value["execution"] = {
            "auto_workspace_policy": policy,
            "merge_failure_limit": merge_limit,
            "allow_concurrent_main_tasks": concurrent,
        }

        appearance = str(interface.get("appearance") or "").strip()
        theme = str(interface.get("theme") or "").strip()
        motion = str(interface.get("motion") or "").strip()
        if appearance not in APPEARANCES:
            raise ValueError("Invalid appearance")
        if theme not in THEMES:
            raise ValueError("Invalid theme")
        if motion not in MOTIONS:
            raise ValueError("Invalid motion preference")
        value["interface"] = {
            "appearance": appearance,
            "theme": theme,
            "motion": motion,
        }

        language = str(raw.get("language") or "").strip()
        if language not in LANGUAGES:
            raise ValueError("Invalid language")
        value["language"] = language

        mode = str(defaults.get("mode") or "").strip()
        reasoning = str(defaults.get("reasoning") or "").strip()
        if mode not in MODES:
            raise ValueError("Invalid default mode")
        if reasoning not in REASONING_LEVELS:
            raise ValueError("Invalid default reasoning")
        value["defaults"] = {
            "agent": cls._text(defaults.get("agent"), "Default Agent", 120),
            "model": cls._text(defaults.get("model"), "Default Model", 240),
            "mode": mode,
            "reasoning": reasoning,
            "workflow": cls._text(defaults.get("workflow"), "Default Workflow"),
        }
        return value

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
