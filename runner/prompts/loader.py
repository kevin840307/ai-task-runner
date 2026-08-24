"""Load and strictly render bundled/project prompt templates."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, meta

from ..project.policy import instruction_text
from ..errors import RunnerError
from ..plugins.registry import collect_plugin_instructions
from . import PROMPT_ROOT

_ENV = Environment(
    loader=FileSystemLoader(str(PROMPT_ROOT)),
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
)


def _resolve(filename: str, base: Path) -> Path:
    path = Path(filename).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def render_prompt(filename: str, values: dict[str, Any] | None = None, *, base: Path = PROMPT_ROOT) -> str:
    """Render one prompt with Jinja StrictUndefined; missing variables fail immediately."""
    path = _resolve(filename, base)
    if not path.is_file():
        raise RunnerError(f"missing prompt template: {path}")
    try:
        if path.is_relative_to(PROMPT_ROOT):
            template = _ENV.get_template(path.relative_to(PROMPT_ROOT).as_posix())
        else:
            template = _ENV.from_string(path.read_text(encoding="utf-8-sig"))
        return template.render(**(values or {}))
    except OSError as error:
        raise RunnerError(f"cannot read prompt template: {path}: {error}") from error
    except Exception as error:
        raise RunnerError(f"cannot render prompt template: {path}: {error}") from error


def prompt_variables(filename: str, *, base: Path = PROMPT_ROOT) -> set[str]:
    """Return undeclared top-level Jinja variables for contract tests/tooling."""
    path = _resolve(filename, base)
    if not path.is_file():
        raise RunnerError(f"missing prompt template: {path}")
    try:
        source = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise RunnerError(f"cannot read prompt template: {path}: {error}") from error
    return set(meta.find_undeclared_variables(_ENV.parse(source)))


def always_instructions(root: Path) -> str:
    text = instruction_text(root, "always")
    return f"\nUser-enforced instructions (apply to this call):\n{text}\n" if text else ""


def ai_rules(root: Path) -> str:
    return render_prompt("system/rules.md", {
        "project": {"root": str(root)},
        "plugin_rules": collect_plugin_instructions(root),
    }) + always_instructions(root)


def structured_retry_prompt(error: str) -> str:
    return render_prompt("system/structured_output_retry.md", {
        "error": error.strip()[-500:] or "invalid structured output",
    })


__all__ = [
    "ai_rules",
    "always_instructions",
    "prompt_variables",
    "render_prompt",
    "structured_retry_prompt",
]
