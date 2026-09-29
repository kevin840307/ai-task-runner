"""Resource I/O plus durable frozen Workflow/Prompt assets."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .errors import ConfigurationError, RunnerError
from .utils import io_path

Validator = Callable[[str], None]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path: str | Path) -> tuple[str, str]:
    source = Path(path).expanduser().resolve()
    try:
        text = io_path(source).read_text(encoding="utf-8-sig")
    except OSError as error:
        raise RunnerError(f"cannot read resource: {source}: {error}") from error
    return text, text_hash(text)


def _check_expected_hash(path: Path, expected_hash: str | None) -> None:
    if expected_hash is not None and (
        not io_path(path).exists() or read_text(path)[1] != expected_hash
    ):
        raise RunnerError(f"resource changed since it was read: {path}")


def write_text(
    path: str | Path,
    text: str,
    *,
    expected_hash: str | None = None,
    validate: Validator | None = None,
) -> str:
    """Validate and atomically replace one UTF-8 text resource."""
    if not isinstance(text, str):
        raise ValueError("resource text must be a string")  # noqa: TRY004
    target = Path(path).expanduser().resolve()
    if validate is not None:
        validate(text)
    _check_expected_hash(target, expected_hash)
    io_path(target.parent).mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        io_path(temp).write_text(text, encoding="utf-8")
        os.replace(io_path(temp), io_path(target))
    except OSError as error:
        try:
            io_path(temp).unlink(missing_ok=True)
        except OSError:
            pass
        raise RunnerError(f"cannot write resource: {target}: {error}") from error
    return text_hash(text)


def delete(path: str | Path, *, expected_hash: str | None = None) -> None:
    target = Path(path).expanduser().resolve()
    _check_expected_hash(target, expected_hash)
    try:
        io_path(target).unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise RunnerError(f"cannot delete resource: {target}: {error}") from error


__all__ = ["delete", "read_text", "text_hash", "write_text"]

SNAPSHOT_FILE = "workflow.snapshot.json"
RESOURCE_DIR = "resources"
RUN_RESOURCE_FILES = {
    "goal": "goal.txt",
    "ai_validator_prompt": "ai-validator-prompt.txt",
}

def snapshot_path(project_root: str | Path, work_dir: str | Path) -> Path:
    return Path(project_root).resolve() / work_dir / SNAPSHOT_FILE


def load_snapshot(
    project_root: str | Path,
    work_dir: str | Path,
) -> list[dict[str, Any]] | None:
    path = snapshot_path(project_root, work_dir)
    if not io_path(path).is_file():
        return None
    try:
        workflow = json.loads(io_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(
            f"invalid workflow snapshot: {path}: {error}"
        ) from error
    try:
        _validate_snapshot(workflow)
    except RunnerError as error:
        raise ConfigurationError(
            f"invalid workflow snapshot: {path}: {error}"
        ) from error
    return workflow


def run_resource_path(
    project_root: str | Path,
    work_dir: str | Path,
    name: str,
) -> Path:
    try:
        filename = RUN_RESOURCE_FILES[name]
    except KeyError as error:
        raise ValueError(f"unknown run resource: {name}") from error
    return (
        Path(project_root).resolve()
        / work_dir
        / RESOURCE_DIR
        / filename
    )


def load_run_resource(
    project_root: str | Path,
    work_dir: str | Path,
    name: str,
) -> tuple[str, str] | None:
    path = run_resource_path(project_root, work_dir, name)
    if not io_path(path).is_file():
        return None
    try:
        return (
            str(path.resolve()),
            io_path(path).read_text(encoding="utf-8-sig"),
        )
    except OSError as error:
        raise ConfigurationError(
            f"cannot read run resource: {path}: {error}"
        ) from error


def freeze_run_resource(
    source: str | Path | None,
    project_root: str | Path,
    work_dir: str | Path,
    name: str,
) -> tuple[str, str] | None:
    if not source:
        return None
    path = Path(source).expanduser()
    try:
        text = io_path(path).read_text(encoding="utf-8-sig")
    except OSError as error:
        raise ConfigurationError(
            f"cannot snapshot {name}: {path}: {error}"
        ) from error
    target = run_resource_path(project_root, work_dir, name)
    write_text(target, text)
    return str(target.resolve()), text


def freeze_workflow(
    workflow: list[dict[str, Any]],
    project_root: str | Path,
    work_dir: str | Path,
) -> list[dict[str, Any]]:
    work = Path(project_root).resolve() / work_dir
    frozen = deepcopy(workflow)
    _snapshot_prompts(frozen, work / RESOURCE_DIR)
    payload = json.dumps(
        frozen,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    write_text(work / SNAPSHOT_FILE, payload)
    return frozen


def _snapshot_prompts(value: Any, resources: Path) -> None:
    if isinstance(value, list):
        for item in value:
            _snapshot_prompts(item, resources)
        return
    if not isinstance(value, dict):
        return
    prompt = value.get("prompt")
    if isinstance(prompt, str):
        path = Path(prompt).expanduser()
        if path.is_absolute() and io_path(path).is_file():
            try:
                text = io_path(path).read_text(encoding="utf-8-sig")
            except OSError as error:
                raise RunnerError(
                    f"cannot snapshot prompt: {path}: {error}"
                ) from error
            target = resources / f"{text_hash(text)}{path.suffix or '.txt'}"
            if not io_path(target).is_file():
                write_text(target, text)
            value["prompt"] = str(target.resolve())
    for child in value.values():
        _snapshot_prompts(child, resources)


def _validate_snapshot(workflow: Any) -> None:
    # Lazy import avoids registry -> Stage -> lifecycle -> schema cycles.
    from .workflow.schema import validate_stage, validate_topology

    if not isinstance(workflow, list) or not workflow:
        raise RunnerError("workflow snapshot must be a non-empty list")
    for item in workflow:
        if not isinstance(item, dict):
            raise RunnerError("workflow snapshot contains an invalid Stage")
        values = {
            key: value
            for key, value in item.items()
            if key != "_workflow_index"
        }
        validate_stage(str(item.get("name", "")), values)
    validate_topology(workflow)

__all__ = [
    "RESOURCE_DIR",
    "SNAPSHOT_FILE",
    "delete",
    "freeze_run_resource",
    "freeze_workflow",
    "load_run_resource",
    "load_snapshot",
    "read_text",
    "run_resource_path",
    "snapshot_path",
    "text_hash",
    "write_text",
]
