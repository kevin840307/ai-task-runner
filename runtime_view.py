"""Canonical read-only runtime projection shared by UI surfaces.

This module does not own runtime state or transitions. It projects existing
Runner/process evidence into one consistent status/action contract.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_STATUS_LABELS = {
    "idle": "Idle",
    "running": "Running",
    "recovering": "Recovering",
    "stopped": "Stopped",
    "completed": "Completed",
    "needs_attention": "Needs Attention",
    "missing": "Missing",
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _recovery(evidence: Mapping[str, Any], *, active: bool) -> dict[str, Any]:
    raw = evidence.get("recovery")
    data = raw if isinstance(raw, Mapping) else {}
    error = _text(data.get("error")) or _text(evidence.get("last_error"))
    try:
        retry = max(0, int(data.get("retry") or 0))
    except (TypeError, ValueError):
        retry = 0
    try:
        wait_seconds = max(0.0, float(data.get("wait_seconds") or 0))
    except (TypeError, ValueError):
        wait_seconds = 0.0
    return {
        "active": active,
        "mode": _text(data.get("retry_mode")),
        "retry": retry,
        "wait_seconds": wait_seconds,
        "error": error,
    }


def build_runtime_view(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Project durable/process evidence without creating a second state machine."""
    exists = bool(evidence.get("project_exists", True))
    running = bool(evidence.get("running"))
    completed = bool(evidence.get("completed"))
    resumable = bool(evidence.get("resumable"))
    stale = bool(evidence.get("stale"))
    last_error = _text(evidence.get("last_error"))
    raw_recovery = evidence.get("recovery")
    has_recovery = isinstance(raw_recovery, Mapping) and bool(raw_recovery)
    recovering = running and (has_recovery or last_error or _text(evidence.get("cli_status")).lower() == "recovering")

    if not exists:
        status = "missing"
    elif recovering:
        status = "recovering"
    elif running:
        status = "running"
    elif completed:
        status = "completed"
    elif resumable and (stale or last_error):
        status = "needs_attention"
    elif resumable:
        status = "stopped"
    else:
        status = "idle"

    can_rerun = bool(evidence.get("can_rerun"))
    resettable = bool(evidence.get("resettable"))
    actions = {
        "run": bool(exists and not running and not resumable),
        "stop": bool(exists and running),
        "resume": bool(exists and not running and resumable),
        "reset": bool(exists and not running and (resumable or resettable)),
        "rerun": bool(exists and not running and completed and can_rerun),
    }

    reason = ""
    recommended: list[str] = []
    if status == "recovering":
        recovery = _recovery(evidence, active=True)
        reason = recovery["error"] or "A technical error is being retried automatically."
        recommended = ["stop"]
    elif status == "needs_attention":
        transition = evidence.get("last_transition")
        transition_data = transition if isinstance(transition, Mapping) else {}
        if _text(transition_data.get("status")).lower() == "fail":
            stage = _text(transition_data.get("stage")) or "Stage"
            reason = f"{stage} returned FAIL and the Workflow did not continue."
            recommended = ["open_workflow", "view_trace"]
            if actions["reset"]:
                recommended.append("reset")
        else:
            if stale:
                reason = "The Runner process is no longer active before this run completed."
            else:
                reason = last_error or "This run stopped before completion and needs a decision."
            recommended = [name for name in ("resume", "reset") if actions[name]]
        recovery = _recovery(evidence, active=False)
    elif status == "stopped":
        reason = "This run is stopped before completion."
        recommended = [name for name in ("resume", "reset") if actions[name]]
        recovery = _recovery(evidence, active=False)
    else:
        recovery = _recovery(evidence, active=False)

    request = evidence.get("request")
    request_data = request if isinstance(request, Mapping) else {}
    current_model = evidence.get("effective_model")
    current_backend = evidence.get("effective_backend")
    snapshot = {
        "run_id": _text(evidence.get("run_id")),
        "started_at": evidence.get("started_at") or 0,
        "updated_at": evidence.get("updated_at") or 0,
        "workflow": _text(request_data.get("workflow") or evidence.get("workflow")),
        "backend": _text(request_data.get("backend") or evidence.get("backend")),
        "model": _text(request_data.get("model") or evidence.get("model")),
        "validator": _text(request_data.get("validator") or evidence.get("validator")),
        "readonly_safety": _text(request_data.get("readonly_safety")),
        "effective_backend": _text(current_backend),
        "effective_model": _text(current_model),
    }

    return {
        "status": status,
        "label": _STATUS_LABELS[status],
        "needs_attention": status == "needs_attention",
        "reason": reason,
        "recommended_actions": recommended,
        "actions": actions,
        "recovery": recovery,
        "current": {
            "stage": _text(evidence.get("stage")),
            "task": _text(evidence.get("task")),
            "cycle": int(evidence.get("cycle") or 1),
            "current": int(evidence.get("current") or 0),
            "total": int(evidence.get("total") or 0),
            "completed_count": int(evidence.get("completed_count") or 0),
        },
        "run": snapshot,
    }


__all__ = ["build_runtime_view"]
