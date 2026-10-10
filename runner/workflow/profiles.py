"""AI Stage profile defaults shared by runtime, YAML normalization, and Studio."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

AI_STAGE_PROFILES: dict[str, dict[str, Any]] = {
    "generic": {
        "semantics": "generic",
        "title": "Generic",
        "description": "General-purpose AI Stage with no task/review semantics.",
        "defaults": {
            "prompt": "common/generic.md",
        },
        "test_examples": {
            "pass": "Reply with a concise confirmation that this isolated AI Stage test ran successfully.",
            "fail": "Reply that the isolated test condition is not satisfied and give one concrete reason.",
            "error": "Technical ERROR is injected by the Stage Test harness; retry then executes the real AI Stage.",
        },
    },
    "execute": {
        "semantics": "execute",
        "title": "Execute",
        "description": "Writable task execution Stage using the shared execution prompt.",
        "defaults": {
            "status": "AI 正在處理目前任務",
            "prompt": "common/execution.md",
            "run_state": "executing",
            "mode": "write",
            "actor": "executor",
            "allow_project_read": True,
            "track_changes": True,
        },
        "test_examples": {
            "pass": "Create a small file named stage_test.txt containing exactly STAGE_TEST_OK. Keep the change limited to this isolated Stage test.",
            "fail": "Do not satisfy the isolated task acceptance criterion. Explain what remains incomplete without pretending it is finished.",
            "error": "Technical ERROR is injected by the Stage Test harness before the real Execute-profile AI Stage runs.",
        },
    },
    "review": {
        "semantics": "review",
        "title": "Review",
        "description": "Read-only semantic review gate with fail-soft technical retry policy.",
        "defaults": {
            "status": "AI 正在確認任務是否完成",
            "prompt": "common/review.md",
            "run_state": "reviewing",
            "mode": "readonly",
            "allow_project_read": True,
            "readonly_safety": "observe",
            "error_policy": {"retries": 2},
            "max_failures": 3,
        },
        "test_examples": {
            "pass": "Treat the isolated task evidence as complete and return the normal Review PASS contract with no missing items.",
            "fail": "Treat one concrete acceptance criterion as unsatisfied and return the normal Review FAIL contract with one actionable missing item.",
            "error": "Technical ERROR is injected by the Stage Test harness; retry then executes the real Review-profile AI Stage.",
        },
    },
}


def profile_names() -> list[str]:
    return list(AI_STAGE_PROFILES)


def profile_defaults(profile: str) -> dict[str, Any]:
    item = AI_STAGE_PROFILES.get(str(profile or "generic"))
    return deepcopy(item.get("defaults", {})) if item else {}



def profile_semantics(profile: str) -> str:
    item = AI_STAGE_PROFILES.get(str(profile or "generic"))
    return str(item.get("semantics", "") or "") if item else ""


def stage_profile_semantics(definition: dict[str, Any]) -> str:
    if str(definition.get("type", "base")) != "base":
        return ""
    return profile_semantics(str(definition.get("profile", "generic") or "generic"))


def apply_ai_profile_defaults(definition: dict[str, Any]) -> dict[str, Any]:
    """Apply only missing AI profile values; explicit YAML always wins."""
    if str(definition.get("type", "base")) != "base":
        return definition
    profile = str(definition.get("profile", "generic") or "generic")
    defaults = profile_defaults(profile)
    for key, value in defaults.items():
        definition.setdefault(key, value)
    definition["profile"] = profile
    return definition


__all__ = [
    "AI_STAGE_PROFILES",
    "apply_ai_profile_defaults",
    "profile_defaults",
    "profile_names",
    "profile_semantics",
    "stage_profile_semantics",
]
