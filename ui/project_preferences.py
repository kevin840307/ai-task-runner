"""Durable Project-scoped UI preferences.

The browser keeps only an in-memory projection. This module is the persistence
owner for settings shared by all Chat sessions in one Project, plus the legacy
Runner validator picker values that already belong to that same Project.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

PREFERENCES_FILE = ".ai-task-runner/ui/project-preferences.json"
PREFERENCES_VERSION = 1
VALID_MODES = {"read", "auto", "yolo"}
VALID_REASONING = {"low", "medium", "high", "xhigh", "max"}


class ProjectPreferences:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def get(self, project: Path) -> dict[str, Any]:
        with self._lock:
            path = self._path(project)
            value = self._load(path) if path.exists() else self._defaults()
            return {**value, "exists": path.exists()}

    def update(self, project: Path, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "agent",
            "model",
            "mode",
            "reasoning",
            "workflow",
            "validators",
            "ai_validator_prompts",
        }
        unknown = set(patch) - allowed - {"project"}
        if unknown:
            raise ValueError(f"Unknown Project preference: {sorted(unknown)[0]}")
        with self._lock:
            path = self._path(project)
            value = self._load(path) if path.exists() else self._defaults()
            if "agent" in patch:
                value["agent"] = self._text(patch["agent"], "Agent", 120)
            if "model" in patch:
                value["model"] = self._text(patch["model"], "Model", 240)
            if "workflow" in patch:
                value["workflow"] = self._text(patch["workflow"], "Workflow", 4096)
            if "mode" in patch:
                mode = str(patch["mode"] or "").strip().lower()
                if mode not in VALID_MODES:
                    raise ValueError("Mode must be read, auto, or yolo")
                value["mode"] = mode
            if "reasoning" in patch:
                reasoning = str(patch["reasoning"] or "").strip().lower()
                if reasoning not in VALID_REASONING:
                    raise ValueError("Unsupported reasoning level")
                value["reasoning"] = reasoning
            if "validators" in patch:
                value["validators"] = self._string_map(
                    patch["validators"], "Validator", value_limit=4096
                )
            if "ai_validator_prompts" in patch:
                value["ai_validator_prompts"] = self._string_map(
                    patch["ai_validator_prompts"], "AI validator prompt", value_limit=4096
                )
            self._write(path, value)
            return {**value, "exists": True}

    def _load(self, path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Project preferences are invalid: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("version") != PREFERENCES_VERSION:
            raise ValueError("Unsupported Project preferences version")
        value = self._defaults()
        value["agent"] = self._text(raw.get("agent", ""), "Agent", 120)
        value["model"] = self._text(raw.get("model", ""), "Model", 240)
        value["workflow"] = self._text(raw.get("workflow", ""), "Workflow", 4096)
        mode = str(raw.get("mode", "auto") or "").strip().lower()
        reasoning = str(raw.get("reasoning", "medium") or "").strip().lower()
        if mode not in VALID_MODES or reasoning not in VALID_REASONING:
            raise ValueError("Project preferences contain an unsupported mode or reasoning level")
        value["mode"] = mode
        value["reasoning"] = reasoning
        value["validators"] = self._string_map(raw.get("validators", {}), "Validator", 4096)
        value["ai_validator_prompts"] = self._string_map(
            raw.get("ai_validator_prompts", {}), "AI validator prompt", 4096
        )
        return value

    @staticmethod
    def _defaults() -> dict[str, Any]:
        return {
            "version": PREFERENCES_VERSION,
            "agent": "",
            "model": "",
            "mode": "auto",
            "reasoning": "medium",
            "workflow": "",
            "validators": {},
            "ai_validator_prompts": {},
        }

    @staticmethod
    def _text(value: Any, label: str, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) > limit:
            raise ValueError(f"{label} preference is too long")
        return text

    @classmethod
    def _string_map(
        cls,
        value: Any,
        label: str,
        value_limit: int,
    ) -> dict[str, str]:
        if not isinstance(value, dict):
            raise ValueError(f"{label} preferences must be an object")
        result: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = cls._text(raw_key, f"{label} key", 4096)
            item = cls._text(raw_value, label, value_limit)
            if key:
                result[key] = item
        return result

    @staticmethod
    def _path(project: Path) -> Path:
        return project / PREFERENCES_FILE

    @staticmethod
    def _write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
