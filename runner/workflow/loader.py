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
    workflow_has_planning,
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
    _inject_planner_catalog(stages, raw_flow, source)
    result = _normalize_sequence(raw_flow, stages, top_level=True, source=source)
    validate_topology(result)
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
    _resolve_local_prompt(values, source)
    validate_stage(name, values)
    return values


def _inject_planner_catalog(
    stages: dict[str, dict[str, Any]], raw_flow: Any, source: Path
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
        name: _normalize_invocation(name, stages, (), source)
        for name in candidates
    }
    for definition in plans:
        definition["planner_stages"] = deepcopy(catalog)
        validate_stage(definition["name"], definition)


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


def _resolve_local_prompt(values: dict[str, Any], source: Path) -> None:
    value = values.get("prompt")
    if not isinstance(value, str) or not value.strip():
        return
    path = Path(value).expanduser()
    if path.is_absolute():
        return
    local = source.parent / path
    if local.is_file():
        values["prompt"] = str(local.resolve())


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
    node.update(overrides)
    _resolve_local_prompt(node, source)
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
    "workflow_has_planning",
    "workflow_validators",
]
