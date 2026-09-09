from pathlib import Path

import pytest

from runner.errors import RunnerError
from runner.prompts import PROMPT_ROOT
from runner.prompts.context import PROMPT_CONTEXT_KEYS
from runner.prompts.loader import prompt_variables, render_prompt

SYSTEM_ONLY_KEYS = {"plugin_rules"}
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


def test_review_prompts_keep_behavior_delta_while_protocol_owns_invariants():
    from runner.prompts.protocols import REVIEW_PROTOCOL

    review = (PROMPT_ROOT / "stages" / "review.md").read_text(encoding="utf-8")
    continuation = (PROMPT_ROOT / "stages" / "review_continue.md").read_text(encoding="utf-8")

    assert "current TODO only" in review
    assert "adequate evidence" in review
    assert "Do not reuse the previous verdict" in continuation
    assert "Do not repeat a previous missing item if it is now satisfied" in continuation
    assert "Do not modify, repair, write, edit" in REVIEW_PROTOCOL
    assert "Do not inspect workflow, Runner state, prompts, or validator implementation" in REVIEW_PROTOCOL
    assert "Do not repeat the same successful read/tool call" in REVIEW_PROTOCOL
    assert "if a repeated read reports `Unchanged`" in REVIEW_PROTOCOL
    assert "Do not fail for style preferences" in REVIEW_PROTOCOL


def test_immutable_protocols_own_structured_contracts():
    from runner.prompts.protocols import (
        PLAN_PROTOCOL, REVIEW_PROTOCOL, VALIDATION_PROTOCOL, STRUCTURED_RETRY_PROTOCOL,
    )

    assert "RUNNER_IMMUTABLE_PLAN_PROTOCOL" in PLAN_PROTOCOL
    assert '"tasks"' in PLAN_PROTOCOL
    assert "Complex, cross-file, cross-module, cross-project" in PLAN_PROTOCOL
    assert "RUNNER_IMMUTABLE_REVIEW_PROTOCOL" in REVIEW_PROTOCOL
    assert '"completed"' in REVIEW_PROTOCOL
    assert "RUNNER_IMMUTABLE_VALIDATION_PROTOCOL" in VALIDATION_PROTOCOL
    assert '"passed"' in VALIDATION_PROTOCOL
    assert "RUNNER_IMMUTABLE_STRUCTURED_RETRY" in STRUCTURED_RETRY_PROTOCOL
    assert "never invent a missing item" in STRUCTURED_RETRY_PROTOCOL.lower()

def test_ai_validator_prompt_is_readonly_and_tool_bounded():
    prompt = (PROMPT_ROOT / "stages" / "ai_validator.md").read_text(encoding="utf-8")

    assert "Final validation. This is a fresh independent read-only session." in prompt
    assert "do not modify files, run shell/write/edit tools" in prompt
    assert "create tasks, search for tools, or ask for unavailable tools" in prompt
    assert "focused read-only checks" in prompt


def test_planning_contract_is_code_owned_and_duplicate_task_rules_are_removed():
    from runner.prompts.protocols import PLAN_PROTOCOL

    assert "observable deliverable" in PLAN_PROTOCOL
    assert "acceptance criteria" in PLAN_PROTOCOL
    assert "Runner owns orchestration" in PLAN_PROTOCOL
    assert not (PROMPT_ROOT / "stages" / "plan_task_rules.md").exists()


def test_ai_validator_stage_always_injects_run_level_validation_resource():
    from types import SimpleNamespace
    from runner.workflow.stages.ai_stage import AIValidatorStage, AIValidatorStageSpec

    stage = AIValidatorStage(AIValidatorStageSpec(name="validate_ai"))
    ctx = SimpleNamespace(config=SimpleNamespace(ai_validator_prompt="CHECK_MAGIC_BUSINESS_RULE"))
    custom_template_output = "Custom validator template that forgot validation.instructions."
    rendered = stage._augment_rendered_prompt(ctx, custom_template_output)

    assert "CHECK_MAGIC_BUSINESS_RULE" in rendered
    assert "Runner-provided AI validation resource (required):" in rendered
    assert stage._augment_rendered_prompt(ctx, rendered) == rendered
