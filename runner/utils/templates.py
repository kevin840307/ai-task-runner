"""Generic resource/file template helpers."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any

from jinja2 import Environment, StrictUndefined

from ..errors import RunnerError

_JINJA = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)


def render_resource(package: str, name: str, values: dict[str, Any] | None = None) -> str:
    path = files(package) / name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RunnerError(f"missing template resource: {package}/{name}") from error
    return Template(text).safe_substitute({key: str(value) for key, value in (values or {}).items()})


def render_prompt_file(filename: str, values: dict[str, Any], *, base: Path) -> str:
    """Render a project-defined prompt path with generic Jinja variables."""
    path = Path(filename).expanduser()
    if not path.is_absolute():
        path = (base / path).resolve()
    if not path.is_file():
        raise RunnerError(f"missing stage prompt: {path}")
    try:
        template = _JINJA.from_string(path.read_text(encoding="utf-8-sig"))
        return template.render(**values)
    except OSError as error:
        raise RunnerError(f"cannot read stage prompt: {path}: {error}") from error
    except Exception as error:
        raise RunnerError(f"cannot render stage prompt: {path}: {error}") from error


def append_resource(prompt: str, package: str, name: str) -> str:
    return prompt.rstrip() + "\n\n" + render_resource(package, name).strip() + "\n"


__all__ = ["append_resource", "render_prompt_file", "render_resource"]
