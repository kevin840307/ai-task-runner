"""Load declarative Workflow YAML into normalized Stage nodes."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..errors import RunnerError
from ..resources import write_text
from ..utils.files import io_path
from .schema import (
    validate_routes,
    validate_stage,
    validate_topology,
    workflow_has_task_producer,
    workflow_validators,
)

WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "workflows"
WORKFLOWS = {
    "mixed": WORKFLOW_DIR / "mixed.yaml",
    "file": WORKFLOW_DIR / "file.yaml",
    "ai": WORKFLOW_DIR / "ai.yaml",
    "workflow_builder": WORKFLOW_DIR / "workflow_builder.yaml",
    "ralphy_ai_validate": WORKFLOW_DIR / "ralphy_ai_validate.yaml",
}
DEFAULT_WORKFLOW = WORKFLOWS["mixed"]


def load_workflow(path: str | Path | None = None) -> list[dict[str, Any]]:
    source = Path(path).expanduser() if path else DEFAULT_WORKFLOW
    try:
        import yaml
        data = yaml.safe_load(io_path(source).read_text(encoding="utf-8"))
    except ImportError as error:
        raise RunnerError("Workflow YAML requires PyYAML: pip install PyYAML") from error
    except (OSError, yaml.YAMLError) as error:
        raise RunnerError(f"invalid workflow YAML: {error}") from error
    return normalize_workflow(data, source.resolve())


def save_workflow(
    path: str | Path,
    text: str,
    *,
    expected_hash: str | None = None,
) -> str:
    target = Path(path).expanduser().resolve()

    def validate(source_text: str) -> None:
        try:
            import yaml
            data = yaml.safe_load(source_text)
        except ImportError as error:
            raise RunnerError("Workflow YAML requires PyYAML: pip install PyYAML") from error
        except yaml.YAMLError as error:
            raise RunnerError(f"invalid workflow YAML: {error}") from error
        normalize_workflow(data, target)

    return write_text(target, text, expected_hash=expected_hash, validate=validate)


def load_default_workflow(
    validator: str | None,
    ai_validator_prompt: str = "",
) -> list[dict[str, Any]]:
    return load_workflow(
        WORKFLOWS[default_workflow_name(validator, ai_validator_prompt)]
    )


def default_workflow_name(
    validator: str | None,
    ai_validator_prompt: str = "",
) -> str:
    if isinstance(validator, str) and validator.lower() == "ai":
        return "ai"
    return "mixed" if ai_validator_prompt.strip() else "file"


def normalize_workflow(data: Any, source: Path) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise RunnerError("workflow must be a YAML object")
    unknown = sorted(str(key) for key in data if key not in {"stages", "flow"})
    if unknown:
        raise RunnerError(
            "workflow supports only stages and flow; unknown keys: "
            + ", ".join(unknown)
        )

    raw_stages = data.get("stages")
    raw_flow = data.get("flow")
    if not isinstance(raw_stages, dict) or not raw_stages:
        raise RunnerError("workflow.stages must be a non-empty object")
    if not isinstance(raw_flow, list) or not raw_flow:
        raise RunnerError("workflow.flow must be a non-empty array")

    stages = {
        str(name): _normalize_stage(name, definition, source)
        for name, definition in raw_stages.items()
    }

    names: list[str] = []
    for item in raw_flow:
        if not isinstance(item, str) or not item.strip():
            raise RunnerError("workflow.flow must contain only Stage names")
        name = item.strip()
        if name not in stages:
            raise RunnerError(f"unknown workflow stage: {name}")
        names.append(name)

    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise RunnerError(
            "workflow.flow Stage names must be unique; use routes for loops: "
            + ", ".join(duplicates)
        )

    result = [deepcopy(stages[name]) for name in names]
    for index, node in enumerate(result):
        node["_workflow_index"] = index

    validate_routes(result)
    validate_topology(result)
    return result


def _normalize_stage(name: Any, definition: Any, source: Path) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise RunnerError("workflow stage name must be a non-empty string")
    if not isinstance(definition, dict):
        raise RunnerError(f"workflow stage {name} must be an object")
    values = deepcopy(definition)
    values.setdefault("type", "base")
    values["name"] = name
    instructions_file = values.pop("instructions_file", None)
    if instructions_file is not None:
        values["instructions"] = _read_text(instructions_file, source, name)
    _resolve_local_prompt(values, source)
    validate_stage(name, values)
    return values


def _read_text(value: Any, source: Path, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunnerError(f"workflow stage {name} instructions_file must be non-empty")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = source.parent / path
    try:
        text = io_path(path).read_text(encoding="utf-8-sig").strip()
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


def workflow_fingerprint(workflow: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_WORKFLOW",
    "WORKFLOW_DIR",
    "WORKFLOWS",
    "default_workflow_name",
    "load_default_workflow",
    "load_workflow",
    "normalize_workflow",
    "save_workflow",
    "workflow_fingerprint",
    "workflow_has_task_producer",
    "workflow_validators",
]
