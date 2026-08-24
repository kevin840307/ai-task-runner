from pathlib import Path

import pytest

from runner.errors import RunnerError
from runner.prompts import PROMPT_ROOT
from runner.prompts.context import PROMPT_CONTEXT_KEYS
from runner.prompts.loader import prompt_variables, render_prompt

SYSTEM_ONLY_KEYS = {"error", "plugin_rules"}
ALLOWED_PROMPT_KEYS = PROMPT_CONTEXT_KEYS | SYSTEM_ONLY_KEYS


def test_all_bundled_prompt_variables_use_managed_contract():
    unknown: dict[str, set[str]] = {}
    for path in PROMPT_ROOT.rglob("*.md"):
        variables = prompt_variables(str(path))
        extra = variables - ALLOWED_PROMPT_KEYS
        if extra:
            unknown[path.relative_to(PROMPT_ROOT).as_posix()] = extra
    assert unknown == {}


def test_prompt_templates_do_not_reference_runtime_internal_objects():
    forbidden = {"state", "args", "scratch", "config"}
    offenders = {}
    for path in PROMPT_ROOT.rglob("*.md"):
        used = prompt_variables(str(path)) & forbidden
        if used:
            offenders[path.relative_to(PROMPT_ROOT).as_posix()] = used
    assert offenders == {}


def test_prompt_templates_use_only_jinja_variable_syntax():
    offenders = []
    for path in PROMPT_ROOT.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        if "$goal" in text or "$root" in text or "$planning_" in text:
            offenders.append(path.relative_to(PROMPT_ROOT).as_posix())
    assert offenders == []


def test_strict_undefined_fails_fast(tmp_path):
    template = tmp_path / "bad.md"
    template.write_text("{{ missing_value }}", encoding="utf-8")
    with pytest.raises(RunnerError, match="missing_value"):
        render_prompt(str(template), {})
