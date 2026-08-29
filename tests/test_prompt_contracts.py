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


def test_review_prompts_require_semantically_consistent_pass_fail():
    review = (PROMPT_ROOT / "stages" / "review.md").read_text(encoding="utf-8")
    continuation = (PROMPT_ROOT / "stages" / "review_continue.md").read_text(encoding="utf-8")

    assert "Never invent a `missing_items` entry merely to justify FAIL" in review
    assert "If no concrete missing item exists, return PASS" in review
    assert "do not reuse the previous verdict" in continuation
    assert "Do not repeat a previous missing item if it is now satisfied" in continuation
    assert "If no concrete missing item remains, return PASS" in continuation
    assert "Do not repeat the same successful inspection/tool call" in review
    assert "Do not repeat the same successful inspection/tool call" in continuation


def test_structured_retry_forbids_invented_missing_items():
    retry = (PROMPT_ROOT / "system" / "structured_output_retry.md").read_text(encoding="utf-8")
    assert "if there is no concrete unsatisfied or blocking item, return PASS" in retry
    assert "Never invent placeholder `missing_items` merely to satisfy the schema" in retry
    assert "every missing item must describe a concrete unsatisfied requirement" in retry
