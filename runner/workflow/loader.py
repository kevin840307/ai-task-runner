"""Load declarative Workflow YAML into normalized flow nodes."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..errors import RunnerError
from ..resources import write_text
from .schema import (
    validate_restart_targets,
    validate_stage,
    validate_topology,
    workflow_has_task_producer,
    workflow_validators,
)
BUILTIN_WORKFLOW_DIR = Path(__file__).with_name("builtin")
BUILTIN_WORKFLOWS = {
    "mixed": BUILTIN_WORKFLOW_DIR / "mixed.yaml",
    "file": BUILTIN_WORKFLOW_DIR / "file.yaml",
    "ai": BUILTIN_WORKFLOW_DIR / "ai.yaml",
}
DEFAULT_WORKFLOW = BUILTIN_WORKFLOWS["mixed"]


def load_workflow(path: str | Path | None = None) -> list[dict[str, Any]]:
    source = Path(path).expanduser() if path else DEFAULT_WORKFLOW
    try:
        import yaml
    except ImportError as error:
        raise RunnerError("Workflow YAML requires PyYAML: pip install PyYAML") from error
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RunnerError(f"invalid workflow YAML: {error}") from error
    return normalize_workflow(data, source.resolve())



def save_workflow(
    path: str | Path,
    text: str,
    *,
    expected_hash: str | None = None,
) -> str:
    """Validate Workflow text with the real loader contract, then atomically save it."""
    target = Path(path).expanduser().resolve()

    def validate(source_text: str) -> None:
        try:
            import yaml
        except ImportError as error:
            raise RunnerError("Workflow YAML requires PyYAML: pip install PyYAML") from error
        try:
            data = yaml.safe_load(source_text)
        except yaml.YAMLError as error:
            raise RunnerError(f"invalid workflow YAML: {error}") from error
        normalize_workflow(data, target)

    return write_text(target, text, expected_hash=expected_hash, validate=validate)

def load_default_workflow(
    validator: str | None, ai_validator_prompt: str = ""
) -> list[dict[str, Any]]:
    return load_workflow(BUILTIN_WORKFLOWS[
        default_workflow_name(validator, ai_validator_prompt)
    ])


def default_workflow_name(
    validator: str | None,
    ai_validator_prompt: str = "",
) -> str:
    if isinstance(validator, str) and validator.lower() == "ai":
        return "ai"
    if ai_validator_prompt.strip():
        return "mixed"
    return "file"


def normalize_workflow(data: Any, source: Path) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise RunnerError("workflow must be a YAML object")
    unknown = sorted(str(key) for key in data if key not in {"stages", "flow"})
    if unknown:
        raise RunnerError(
            f"workflow supports only stages and flow; unknown keys: {', '.join(unknown)}"
        )
    raw_stages, raw_flow = data.get("stages", {}), data.get("flow")
    if not isinstance(raw_stages, dict):
        raise RunnerError("workflow.stages must be an object")

    stages = {
        str(name): _normalize_stage(name, definition, source)
        for name, definition in raw_stages.items()
    }
    result = _normalize_sequence(raw_flow, stages, top_level=True, source=source)
    result = _expand_plan_task_flow(result, stages, source)
    for index, node in enumerate(result):
        node["_workflow_index"] = index
    validate_restart_targets(result, True)
    validate_topology(result)
    return result



def _expand_plan_task_flow(
    flow: list[dict[str, Any]],
    stages: dict[str, dict[str, Any]],
    source: Path,
) -> list[dict[str, Any]]:
    """Attach the standard per-TODO SOP after top-level Plan stages.

    PlanStage owns task production, so normal YAML does not need to repeat
    ``execute/review + scope: task``.  Explicit task-scoped nodes are still
    accepted for advanced/custom task producers or custom per-task SOPs.
    """
    result: list[dict[str, Any]] = []
    for index, node in enumerate(flow):
        result.append(node)
        if node.get("type") != "plan" or node.get("repair_plan"):
            continue
        if index + 1 < len(flow) and flow[index + 1].get("scope") == "task":
            continue
        defaults = {"execute": {"type": "task"}, "review": {"type": "review"}}
        for name in ("execute", "review"):
            if name in stages:
                task_node = _normalize_invocation(
                    {"stage": name, "scope": "task"}, stages, (), source
                )
            else:
                task_node = _normalize_stage(name, defaults[name], source)
                task_node["scope"] = "task"
            result.append(task_node)
    return result

def _normalize_stage(name: Any, definition: Any, source: Path) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise RunnerError("workflow stage name must be a non-empty string")
    if not isinstance(definition, dict):
        raise RunnerError(f"workflow stage {name} must be an object")
    if "label" in definition:
        raise RunnerError(f"workflow stage {name} label belongs to flow nodes")
    if "scope" in definition:
        raise RunnerError(f"workflow stage {name} scope belongs to flow nodes")
    values = deepcopy(definition)
    _upgrade_legacy_stage(values)
    values.setdefault("type", "base")
    values["name"] = name
    instructions_file = values.pop("instructions_file", None)
    if instructions_file is not None:
        values["instructions"] = _read_text(instructions_file, source, name)
    _resolve_local_prompts(values, source)
    validate_stage(name, values)
    return values



def _upgrade_legacy_stage(values: dict[str, Any]) -> None:
    """Normalize pre-1.2.56 implementation knobs into semantic Stage types."""
    if "max_results" in values and "repeat" not in values:
        values["repeat"] = values.pop("max_results")

    handler = values.pop("result_handler", None)
    status = values.pop("result_status", None)
    condition = values.pop("condition", None)
    stage_type = values.get("type")
    validator = values.get("validator")

    if not stage_type:
        if handler == "plan":
            stage_type = "plan"
        elif handler == "task":
            stage_type = "task"
        elif handler == "review" or status == "completed":
            stage_type = "review"
        elif validator == "ai" or (handler == "validation" and status == "validation"):
            stage_type = "ai_validator"
        else:
            stage_type = "base"
    elif stage_type == "base" and validator == "ai":
        stage_type = "ai_validator"
    values["type"] = stage_type

    if status not in (None, "completed", "validation"):
        raise RunnerError(f"unsupported legacy result_status: {status}")
    if handler not in (None, "plan", "task", "review", "validation"):
        raise RunnerError(f"unsupported legacy result_handler: {handler}")
    if condition not in (None, "ai_validation"):
        raise RunnerError(f"unsupported legacy condition: {condition}")
    if condition == "ai_validation" and stage_type != "ai_validator":
        raise RunnerError("condition: ai_validation requires an AI validator Stage")

    session_key = values.pop("client_cache_key", None)
    if session_key:
        values.setdefault("session_key", session_key)

    expected_backend = {
        "plan": "planning",
        "review": "review",
        "ai_validator": "review",
    }.get(stage_type, "runtime")
    backend = values.pop("backend_mode", None)
    if backend not in (None, expected_backend):
        raise RunnerError(
            f"legacy backend_mode {backend!r} does not match type: {stage_type}"
        )

    expected_timeout = {
        "plan": "planning_timeout",
        "review": "planning_timeout",
    }.get(stage_type, "agent_timeout")
    timeout_attr = values.pop("timeout_attr", None)
    if timeout_attr not in (None, expected_timeout):
        raise RunnerError(
            f"legacy timeout_attr {timeout_attr!r} is no longer configurable; use timeout"
        )

    expected_retry = "review_retries" if stage_type == "review" else ""
    retry_attr = values.pop("retry_attr", None)
    if retry_attr not in (None, "", expected_retry):
        raise RunnerError(
            f"legacy retry_attr {retry_attr!r} is no longer configurable; use retry"
        )

    runs_field = values.pop("runs_field", None)
    required_field = values.pop("required_passes_field", None)
    if runs_field not in (None, "", "final_ai_validations"):
        raise RunnerError("legacy runs_field is no longer configurable; use runs")
    if required_field not in (None, "", "final_ai_required_passes"):
        raise RunnerError(
            "legacy required_passes_field is no longer configurable; use required_passes"
        )

def _read_text(value: Any, source: Path, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunnerError(f"workflow stage {name} instructions_file must be non-empty")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = source.parent / path
    try:
        text = path.read_text(encoding="utf-8-sig").strip()
    except OSError as error:
        raise RunnerError(f"workflow stage {name} instructions not found: {value}") from error
    if not text:
        raise RunnerError(f"workflow stage {name} instructions must not be empty")
    return text


def _resolve_local_prompts(values: dict[str, Any], source: Path) -> None:
    for key in ("prompt", "continuation_prompt"):
        value = values.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value).expanduser()
        if path.is_absolute():
            continue
        local = source.parent / path
        if local.is_file():
            values[key] = str(local.resolve())


def _normalize_sequence(
    data: Any,
    stages: dict[str, dict[str, Any]],
    *,
    top_level: bool = False,
    stack: tuple[str, ...] = (),
    source: Path,
) -> list[dict[str, Any]]:
    if isinstance(data, str):
        data = [data]
    if not isinstance(data, (list, tuple)) or not data:
        raise RunnerError("workflow flow must be a non-empty YAML array")

    result = []
    for index, item in enumerate(data):
        node = _normalize_invocation(item, stages, stack, source)
        if top_level:
            node["_workflow_index"] = index
        result.append(node)
    validate_restart_targets(result, top_level)
    return result


def _normalize_invocation(
    item: Any,
    stages: dict[str, dict[str, Any]],
    stack: tuple[str, ...],
    source: Path,
) -> dict[str, Any]:
    if isinstance(item, str):
        ref, overrides = item, {}
    elif isinstance(item, dict):
        ref = item.get("stage")
        overrides = {key: value for key, value in item.items() if key != "stage"}
    else:
        raise RunnerError("workflow flow item must be a stage name or object")
    if not isinstance(ref, str) or ref not in stages:
        raise RunnerError(f"unknown workflow stage instance: {ref}")

    node = deepcopy(stages[ref])
    if "skip" in overrides and "skip_on_error" not in overrides:
        overrides["skip_on_error"] = bool(overrides.pop("skip"))
    if "max_results" in overrides and "repeat" not in overrides:
        overrides["repeat"] = overrides.pop("max_results")
    node.update(overrides)
    _resolve_local_prompts(node, source)
    validate_stage(str(node.get("name", ref)), node)
    if node.get("recover"):
        if ref in stack:
            raise RunnerError(f"cyclic workflow routing: {' -> '.join((*stack, ref))}")
        node["recover"] = _normalize_sequence(
            node["recover"], stages, stack=(*stack, ref), source=source
        )
    return node


def workflow_fingerprint(workflow: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "BUILTIN_WORKFLOW_DIR",
    "BUILTIN_WORKFLOWS",
    "DEFAULT_WORKFLOW",
    "default_workflow_name",
    "load_default_workflow",
    "load_workflow",
    "normalize_workflow",
    "save_workflow",
    "workflow_fingerprint",
    "workflow_has_task_producer",
    "workflow_validators",
]
