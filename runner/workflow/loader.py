"""Load one small linear workflow into validated Stage definitions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..errors import RunnerError
from .registry import STAGE_REGISTRY, stage_definition

BUILTIN_WORKFLOWS = {
    "mixed": Path(__file__).with_name("mixed.yaml"),
    "file": Path(__file__).with_name("file.yaml"),
    "ai": Path(__file__).with_name("ai.yaml"),
}
DEFAULT_WORKFLOW = BUILTIN_WORKFLOWS["mixed"]


def load_workflow(path: str | Path | None = None) -> list[dict[str, Any]]:
    source = Path(path).expanduser() if path else DEFAULT_WORKFLOW
    try:
        import yaml
    except ImportError as error:
        raise RunnerError(
            "Workflow YAML requires PyYAML: pip install PyYAML"
        ) from error
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RunnerError(f"invalid workflow YAML: {error}") from error
    return normalize_workflow(data, source.resolve())


def load_default_workflow(
    validator: str | None,
    ai_validator_prompt: str = "",
) -> list[dict[str, Any]]:
    if isinstance(validator, str) and validator.lower() == "ai":
        name = "ai"
    elif ai_validator_prompt.strip():
        name = "mixed"
    else:
        name = "file"
    return load_workflow(BUILTIN_WORKFLOWS[name])


def normalize_workflow(data: Any, source: Path) -> list[dict[str, Any]]:
    if not isinstance(data, list) or not data:
        raise RunnerError("workflow must be a non-empty YAML array")

    result: list[dict[str, Any]] = []
    for index, item in enumerate(data, 1):
        stage_name, options = _stage_item(item, index)
        definition = stage_definition(
            stage_name,
            options,
            source=source,
            index=index,
        )
        definition["_workflow_index"] = index - 1
        result.append(definition)

    _validate_topology(result)
    return result


def workflow_fingerprint(workflow: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def workflow_validators(workflow: list[dict[str, Any]]) -> tuple[bool, bool]:
    has_file = any(
        isinstance(definition, dict) and definition.get("stage") == "validate_file"
        for definition in workflow
    )
    has_ai = any(
        isinstance(definition, dict)
        and definition.get("result_handler") == "handle_final_validation_result"
        for definition in workflow
    )
    return has_file, has_ai


def workflow_has_planning(workflow: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(definition, dict) and definition.get("stage") == "planning"
        for definition in workflow
    )


def _stage_item(item: Any, index: int) -> tuple[str, dict[str, Any]]:
    if isinstance(item, str):
        name, options = item.strip(), {}
    elif isinstance(item, dict):
        name = item.get("stage")
        options = {key: value for key, value in item.items() if key != "stage"}
    else:
        raise RunnerError(f"workflow stage {index} must be a string or object")
    if (
        not isinstance(name, str)
        or name not in STAGE_REGISTRY
        or not STAGE_REGISTRY[name].public
    ):
        raise RunnerError(f"workflow stage {index} is unknown: {name}")
    return name, options


def _validate_topology(workflow: list[dict[str, Any]]) -> None:
    stage_types = [definition["stage"] for definition in workflow]
    plans = [index for index, value in enumerate(stage_types) if value == "planning"]
    files = [
        index for index, value in enumerate(stage_types) if value == "validate_file"
    ]
    finals = [
        index for index, value in enumerate(stage_types) if value == "validate_ai"
    ]
    if len(plans) > 1:
        raise RunnerError("workflow allows at most one planning stage")
    if len(files) > 1 or len(finals) > 1 or not (files or finals):
        raise RunnerError(
            "workflow requires one validate_file, one validate_ai, or both"
        )
    if files and finals and files[0] > finals[0]:
        raise RunnerError("validate_file must run before validate_ai")
    final_index = finals[0] if finals else files[0]
    if final_index != len(workflow) - 1:
        raise RunnerError("workflow must end with its final validation stage")
    for index, definition in enumerate(workflow, 1):
        restart_at = definition.get("restart_at")
        if restart_at is not None and restart_at > index:
            raise RunnerError(
                f"workflow stage {index} restart_at must reference stage 1..{index}"
            )


__all__ = [
    "BUILTIN_WORKFLOWS",
    "DEFAULT_WORKFLOW",
    "load_default_workflow",
    "load_workflow",
    "normalize_workflow",
    "workflow_fingerprint",
    "workflow_has_planning",
    "workflow_validators",
]
