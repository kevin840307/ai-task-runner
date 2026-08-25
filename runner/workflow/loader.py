"""Load declarative Workflow YAML into normalized flow nodes."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
from typing import Any

from ..errors import RunnerError
from .registry import STAGE_REGISTRY

ROUTING_FIELDS = frozenset({"recover", "restart_at"})
META_FIELDS = frozenset({"name", "type", "validator", *ROUTING_FIELDS})
VALIDATORS = frozenset({"file", "ai"})
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
        raise RunnerError("Workflow YAML requires PyYAML: pip install PyYAML") from error
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RunnerError(f"invalid workflow YAML: {error}") from error
    return normalize_workflow(data, source.resolve())


def load_default_workflow(
    validator: str | None, ai_validator_prompt: str = ""
) -> list[dict[str, Any]]:
    name = (
        "ai"
        if isinstance(validator, str) and validator.lower() == "ai"
        else "mixed" if ai_validator_prompt.strip() else "file"
    )
    return load_workflow(BUILTIN_WORKFLOWS[name])


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
    _inject_planner_catalog(stages, raw_flow)
    result = _normalize_sequence(raw_flow, stages, top_level=True)
    _validate_topology(result)
    return result


def _normalize_stage(name: Any, definition: Any, source: Path) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise RunnerError("workflow stage name must be a non-empty string")
    if not isinstance(definition, dict):
        raise RunnerError(f"workflow stage {name} must be an object")
    if "planner_stages" in definition:
        raise RunnerError(f"workflow stage {name} planner_stages is managed internally")
    values = deepcopy(definition)
    values.setdefault("type", "base")
    values["name"] = name
    instructions_file = values.pop("instructions_file", None)
    if instructions_file is not None:
        values["instructions"] = _read_text(instructions_file, source, name)
    _validate_stage(name, values)
    return values


def _inject_planner_catalog(
    stages: dict[str, dict[str, Any]], raw_flow: Any
) -> None:
    plans = [definition for definition in stages.values() if definition.get("type") == "plan"]
    if not plans:
        return

    top_level = _sequence_refs(raw_flow)
    recovery = set()
    for definition in stages.values():
        recovery.update(_sequence_refs(definition.get("recover", ())))

    candidates = [
        name
        for name, definition in stages.items()
        if name not in top_level
        and name not in recovery
        and definition.get("type") != "plan"
        and definition.get("validator") is None
    ]
    if not candidates:
        raise RunnerError("planning workflow requires at least one dynamic Stage")

    catalog = {
        name: _normalize_invocation(name, stages, ())
        for name in candidates
    }
    for definition in plans:
        definition["planner_stages"] = deepcopy(catalog)
        _validate_stage(definition["name"], definition)


def _sequence_refs(data: Any) -> set[str]:
    if isinstance(data, str):
        return {data}
    if not isinstance(data, (list, tuple)):
        return set()
    refs = set()
    for item in data:
        if isinstance(item, str):
            refs.add(item)
        elif isinstance(item, dict) and isinstance(item.get("stage"), str):
            refs.add(item["stage"])
    return refs


def _validate_stage(name: str, values: dict[str, Any]) -> None:
    stage_type = values.get("type")
    if not isinstance(stage_type, str) or stage_type not in STAGE_REGISTRY:
        raise RunnerError(f"workflow stage {name} has unknown type: {stage_type}")
    validator = values.get("validator")
    if validator is not None:
        if validator not in VALIDATORS:
            raise RunnerError(f"workflow stage {name} has invalid validator: {validator}")
        expected = "python" if validator == "file" else "base"
        if stage_type != expected:
            raise RunnerError(
                f"workflow stage {name} validator {validator} requires type: {expected}"
            )
    allowed = {
        field.name for field in fields(STAGE_REGISTRY[stage_type].spec_class)
    } | META_FIELDS
    unknown = sorted(str(key) for key in values if key not in allowed)
    if unknown:
        raise RunnerError(f"workflow stage {name} unknown options: {', '.join(unknown)}")
    _validate_numbers(name, values)


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


def _validate_numbers(name: str, values: dict[str, Any]) -> None:
    retry = values.get("retry")
    if retry is not None and (
        not isinstance(retry, int) or isinstance(retry, bool) or retry < -1
    ):
        raise RunnerError(f"workflow stage {name} retry must be -1 or non-negative")
    runs, required = values.get("runs"), values.get("required_passes")
    if runs is not None and (
        not isinstance(runs, int) or isinstance(runs, bool) or runs <= 0
    ):
        raise RunnerError(f"workflow stage {name} runs must be a positive integer")
    if required is not None and (
        not isinstance(required, int) or isinstance(required, bool) or required < 0
    ):
        raise RunnerError(f"workflow stage {name} required_passes must be non-negative")
    if isinstance(runs, int) and isinstance(required, int) and required > runs:
        raise RunnerError(f"workflow stage {name} required_passes cannot exceed runs")


def _normalize_sequence(
    data: Any,
    stages: dict[str, dict[str, Any]],
    *,
    top_level: bool = False,
    stack: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if isinstance(data, str):
        data = [data]
    if not isinstance(data, (list, tuple)) or not data:
        raise RunnerError("workflow flow must be a non-empty YAML array")

    result = []
    for index, item in enumerate(data):
        node = _normalize_invocation(item, stages, stack)
        if top_level:
            node["_workflow_index"] = index
        result.append(node)
    _validate_restart_targets(result, top_level)
    return result


def _normalize_invocation(
    item: Any,
    stages: dict[str, dict[str, Any]],
    stack: tuple[str, ...],
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
    node.update(overrides)
    _validate_stage(str(node.get("name", ref)), node)
    if node.get("recover"):
        if ref in stack:
            raise RunnerError(f"cyclic workflow routing: {' -> '.join((*stack, ref))}")
        node["recover"] = _normalize_sequence(
            node["recover"], stages, stack=(*stack, ref)
        )
    return node


def _validate_restart_targets(result: list[dict[str, Any]], top_level: bool) -> None:
    for index, definition in enumerate(result, 1):
        restart_at = definition.get("restart_at")
        if restart_at is None:
            continue
        if not top_level:
            raise RunnerError(f"workflow stage {index} restart_at is only valid at top level")
        if not isinstance(restart_at, str) or not restart_at.strip():
            raise RunnerError(
                f"workflow stage {index} restart_at must be a non-empty stage name"
            )
        preceding = {item.get("name") for item in result[:index] if item.get("name")}
        if restart_at not in preceding:
            raise RunnerError(
                f"workflow stage {index} restart_at must reference its own or an earlier stage name"
            )


def workflow_fingerprint(workflow: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def workflow_validators(workflow: list[dict[str, Any]]) -> tuple[bool, bool]:
    return bool(_indexes(workflow, "validator", "file")), bool(
        _indexes(workflow, "validator", "ai")
    )


def workflow_has_planning(workflow: list[dict[str, Any]]) -> bool:
    return bool(_indexes(workflow, "type", "plan"))


def _indexes(workflow: list[dict[str, Any]], field: str, value: str) -> list[int]:
    return [
        index for index, definition in enumerate(workflow) if definition.get(field) == value
    ]


def _validate_topology(workflow: list[dict[str, Any]]) -> None:
    plans = _indexes(workflow, "type", "plan")
    files = _indexes(workflow, "validator", "file")
    finals = _indexes(workflow, "validator", "ai")
    if len(plans) > 1:
        raise RunnerError("workflow allows at most one top-level planning stage")
    if len(files) > 1 or len(finals) > 1 or not (files or finals):
        raise RunnerError("workflow requires one file validator, one AI validator, or both")
    if files and finals and files[0] > finals[0]:
        raise RunnerError("file validation must run before AI validation")
    if (finals[0] if finals else files[0]) != len(workflow) - 1:
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
