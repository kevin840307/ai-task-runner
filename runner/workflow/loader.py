"""Load one small linear workflow into validated Stage definitions."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..errors import RunnerError
from .definitions import STAGES

BUILTIN_WORKFLOWS = {
    "mixed": Path(__file__).with_name("mixed.yaml"),
    "file": Path(__file__).with_name("file.yaml"),
    "ai": Path(__file__).with_name("ai.yaml"),
}
DEFAULT_WORKFLOW = BUILTIN_WORKFLOWS["mixed"]
WORKFLOW_STAGES = {
    "planning": "plan",
    "run_prompt": "run_prompt",
    "review": "review",
    "validate_file": "validate_file",
    "validate_ai": "validate_ai",
}
STAGE_OPTIONS = {
    "planning": frozenset({"retry"}),
    "run_prompt": frozenset({"prompt", "retry"}),
    "review": frozenset({"prompt", "retry", "skip"}),
    "validate_file": frozenset({"retry"}),
    "validate_ai": frozenset({"prompt", "retry", "runs", "required_passes"}),
}


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
        definition = deepcopy(STAGES[WORKFLOW_STAGES[stage_name]])
        definition["name"] = stage_name
        definition["_workflow_index"] = index - 1
        _apply_options(definition, stage_name, options, source, index)
        result.append(definition)

    _validate_topology(result)
    return result


def workflow_fingerprint(workflow: list[dict[str, Any]]) -> str:
    payload = json.dumps(workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def workflow_validators(workflow: list[dict[str, Any]]) -> tuple[bool, bool]:
    has_file = any(
        isinstance(definition, dict)
        and definition.get("stage") == "python_validator"
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
        isinstance(definition, dict) and definition.get("stage") == "plan"
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
    if not isinstance(name, str) or name not in WORKFLOW_STAGES:
        raise RunnerError(f"workflow stage {index} is unknown: {name}")
    unknown = sorted(str(key) for key in options if key not in STAGE_OPTIONS[name])
    if unknown:
        raise RunnerError(
            f"workflow stage {index} unknown options: {', '.join(unknown)}"
        )
    return name, options


def _apply_options(
    definition: dict[str, Any],
    stage_name: str,
    options: dict[str, Any],
    source: Path,
    index: int,
) -> None:
    if "prompt" in options:
        prompt = options["prompt"]
        if not isinstance(prompt, str) or not prompt.strip():
            raise RunnerError(f"workflow stage {index} prompt must be a non-empty string")
        path = Path(prompt).expanduser()
        if not path.is_absolute():
            path = source.parent / path
        try:
            instructions = path.read_text(encoding="utf-8-sig").strip()
        except OSError as error:
            raise RunnerError(f"workflow stage {index} prompt not found: {prompt}") from error
        if not instructions:
            raise RunnerError(f"workflow stage {index} prompt must not be empty")
        definition["instructions"] = instructions
    elif stage_name in {"run_prompt", "review"}:
        raise RunnerError(f"workflow stage {index} requires prompt")

    if "retry" in options:
        definition["retry"] = _retry(options["retry"], index)
        if definition["stage"] != "python_validator":
            definition["retry_attr"] = ""
    if "skip" in options:
        if not isinstance(options["skip"], bool):
            raise RunnerError(f"workflow stage {index} skip must be boolean")
        definition["skip_on_error"] = options["skip"]
    if "runs" in options:
        definition["runs"] = _positive_integer(options["runs"], index, "runs")
        definition["runs_field"] = ""
    if "required_passes" in options:
        required = options["required_passes"]
        if not isinstance(required, int) or isinstance(required, bool) or required < 0:
            raise RunnerError(
                f"workflow stage {index} required_passes must be a non-negative integer"
            )
        definition["required_passes"] = required
        definition["required_passes_field"] = ""
    if (
        "runs" in options
        and "required_passes" in options
        and options["required_passes"] > options["runs"]
    ):
        raise RunnerError(f"workflow stage {index} required_passes cannot exceed runs")


def _retry(value: Any, index: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < -1:
        raise RunnerError(f"workflow stage {index} retry must be -1 or a non-negative integer")
    return value


def _positive_integer(value: Any, index: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RunnerError(f"workflow stage {index} {name} must be a positive integer")
    return value


def _validate_topology(workflow: list[dict[str, Any]]) -> None:
    stage_types = [definition["stage"] for definition in workflow]
    plans = [index for index, value in enumerate(stage_types) if value == "plan"]
    files = [index for index, value in enumerate(stage_types) if value == "python_validator"]
    finals = [
        index
        for index, definition in enumerate(workflow)
        if definition.get("result_handler") == "handle_final_validation_result"
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
