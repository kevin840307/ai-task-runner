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
    assert "Do not repair, update, write, edit, run shell commands" in review
    assert "Do not repair, update, write, edit, run shell commands" in continuation
    assert "search for tools, or ask for unavailable tools" in review
    assert "search for tools, or ask for unavailable tools" in continuation
    assert "Do not inspect workflow, runner state, prompt, or validator implementation files" in review
    assert "Do not inspect workflow, runner state, prompt, or validator implementation files" in continuation
    assert "At most one successful read is allowed per path/range" in review
    assert "At most one successful read is allowed per path/range" in continuation
    assert "If a repeated read reports `Unchanged`" in review
    assert "If a repeated read reports `Unchanged`" in continuation


def test_structured_retry_forbids_invented_missing_items():
    retry = (PROMPT_ROOT / "system" / "structured_output_retry.md").read_text(encoding="utf-8")
    assert "if there is no concrete unsatisfied or blocking item, return PASS" in retry
    assert "Never invent placeholder `missing_items` merely to satisfy the schema" in retry
    assert "every missing item must describe a concrete unsatisfied requirement" in retry


def test_ai_validator_prompt_is_readonly_and_tool_bounded():
    prompt = (PROMPT_ROOT / "stages" / "ai_validator.md").read_text(encoding="utf-8")

    assert "Final validation. This is a fresh independent read-only session." in prompt
    assert "do not modify files, run shell/write/edit tools" in prompt
    assert "create tasks, search for tools, or ask for unavailable tools" in prompt
    assert "focused read-only checks" in prompt


def test_planning_prompts_keep_acceptance_criteria_on_deliverables():
    rules = (PROMPT_ROOT / "stages" / "plan_task_rules.md").read_text(encoding="utf-8")
    contract = (PROMPT_ROOT / "stages" / "plan_output_contract.md").read_text(encoding="utf-8")

    assert "resulting project artifact or behavior now" in rules
    assert "future Stage behavior, review/repair/validator outcomes" in rules
    assert "future Stage behavior, review/repair/validator outcomes" in contract
