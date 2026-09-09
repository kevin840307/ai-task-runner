from pathlib import Path

import pytest

from runner.errors import RunnerError
from runner.prompts.protocols import (
    PLAN_PROTOCOL,
    REVIEW_PROTOCOL,
    VALIDATION_PROTOCOL,
    append_stage_protocol,
    structured_retry_prompt,
)
from runner.workflow.result_parsers import parse_ai_validation, parse_review
from runner.workflow.task_output import decode_tasks


def test_editable_prompt_cannot_remove_review_wire_contract():
    prompt = append_stage_protocol("Be creative. Reply however you want.", "review")
    assert prompt.startswith("Be creative. Reply however you want.")
    assert prompt.rstrip().endswith("[/RUNNER_IMMUTABLE_REVIEW_PROTOCOL]")
    assert '"completed":true' in prompt


def test_editable_prompt_cannot_remove_validation_wire_contract():
    prompt = append_stage_protocol("Return prose only.", "validation")
    assert "Return prose only." in prompt
    assert "RUNNER_IMMUTABLE_VALIDATION_PROTOCOL" in prompt
    assert '"passed":true' in prompt


def test_plan_protocol_keeps_decomposition_and_task_schema_in_code():
    assert "limited-context" in PLAN_PROTOCOL
    assert "independently executable and independently verifiable TODOs" in PLAN_PROTOCOL
    assert "do not split mechanically by file" in PLAN_PROTOCOL.lower()
    assert '"tasks"' in PLAN_PROTOCOL
    assert '"acceptance_criteria"' in PLAN_PROTOCOL


def test_review_parser_rejects_boolean_strings_and_inconsistent_verdicts():
    with pytest.raises(RunnerError, match="must be boolean"):
        parse_review('{"completed":"false","reason":"x","missing_items":["x"]}', None)
    with pytest.raises(RunnerError, match="empty missing_items"):
        parse_review('{"completed":true,"reason":"x","missing_items":["x"]}', None)
    with pytest.raises(RunnerError, match="non-empty missing_items"):
        parse_review('{"completed":false,"reason":"x","missing_items":[]}', None)


def test_validator_parser_rejects_boolean_strings_and_inconsistent_verdicts():
    with pytest.raises(RunnerError, match="must be boolean"):
        parse_ai_validation('{"passed":"false","reason":"x","missing_items":["x"],"checks_run":[],"suggested_checks":[]}')
    with pytest.raises(RunnerError, match="empty missing_items"):
        parse_ai_validation('{"passed":true,"reason":"x","missing_items":["x"],"checks_run":[],"suggested_checks":[]}')
    with pytest.raises(RunnerError, match="non-empty missing_items"):
        parse_ai_validation('{"passed":false,"reason":"x","missing_items":[],"checks_run":[],"suggested_checks":[]}')


def test_plan_decoder_remains_strict_even_if_editable_planning_prompt_changes():
    tasks = decode_tasks({"tasks":[{
        "title":"one", "description":"do one thing", "deliverable":"artifact",
        "acceptance_criteria":["observable result"],
    }]}, cycle=1, minimum=1)
    assert len(tasks) == 1
    with pytest.raises(RunnerError):
        decode_tasks({"tasks":[{"title":"umbrella"}]}, cycle=1, minimum=1)


def test_structured_retry_is_code_owned_and_short():
    prompt = structured_retry_prompt("validator.passed must be boolean")
    assert "RUNNER_IMMUTABLE_STRUCTURED_RETRY" in prompt
    assert "validator.passed must be boolean" in prompt
    assert "Do not redo the task" in prompt
    assert len(prompt) < 1400


def test_legacy_editable_contract_files_are_gone():
    root = Path(__file__).resolve().parents[1] / "runner" / "prompts"
    assert not (root / "stages" / "plan_output_contract.md").exists()
    assert not (root / "stages" / "review_output_contract.md").exists()
    assert not (root / "system" / "structured_output_retry.md").exists()
    assert "RUNNER_IMMUTABLE_PLAN_PROTOCOL" in PLAN_PROTOCOL
    assert "RUNNER_IMMUTABLE_REVIEW_PROTOCOL" in REVIEW_PROTOCOL
    assert "RUNNER_IMMUTABLE_VALIDATION_PROTOCOL" in VALIDATION_PROTOCOL
