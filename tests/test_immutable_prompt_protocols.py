import json
from pathlib import Path

import pytest

from runner.agent import parse_result
from runner.errors import RunnerError
from runner.prompting import (
    PLAN_PROTOCOL,
    DYNAMIC_TASKS_PROTOCOL,
    DYNAMIC_STAGES_PROTOCOL,
    REVIEW_PROTOCOL,
    VALIDATION_PROTOCOL,
    append_stage_protocol,
    structured_retry_prompt,
)
from runner.workflow.results import decode_tasks, parse_ai_validation, parse_review


def _valid_task_payload() -> dict[str, object]:
    return {
        "title": "one",
        "description": "do one thing",
        "deliverable": "artifact",
        "acceptance_criteria": ["observable result"],
    }


def test_plan_decoder_accepts_direct_task_array_without_weakening_task_schema():
    tasks = decode_tasks([_valid_task_payload()], cycle=2, minimum=1)
    assert [task.id for task in tasks] == ["c02-t001"]
    assert tasks[0].title == "one"
    with pytest.raises(RunnerError):
        decode_tasks([{"title": "umbrella"}], cycle=2, minimum=1)


def test_plan_parser_can_use_complete_task_array_inside_broken_object_envelope():
    payload = [_valid_task_payload()]
    malformed = '{"tasks":' + json.dumps(payload, ensure_ascii=False)  # missing outer }
    with pytest.raises(json.JSONDecodeError):
        json.loads(malformed)

    tasks = parse_result(
        malformed, lambda value: decode_tasks(value, cycle=3, minimum=1)
    )
    assert [task.id for task in tasks] == ["c03-t001"]
    assert tasks[0].acceptance_criteria == ["observable result"]


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
    assert "direct task array" in PLAN_PROTOCOL.lower()


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
    tasks = decode_tasks({"tasks": [_valid_task_payload()]}, cycle=1, minimum=1)
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



def test_dynamic_producer_protocols_require_producer_defined_child_stages():
    assert "RUNNER_IMMUTABLE_DYNAMIC_TASKS_PROTOCOL" in DYNAMIC_TASKS_PROTOCOL
    assert '"tasks"' in DYNAMIC_TASKS_PROTOCOL
    assert '"stages"' in DYNAMIC_TASKS_PROTOCOL
    assert "Runner never invents Execute/Review" in DYNAMIC_TASKS_PROTOCOL
    assert "task_complete=true" in DYNAMIC_TASKS_PROTOCOL

    assert "RUNNER_IMMUTABLE_DYNAMIC_STAGES_PROTOCOL" in DYNAMIC_STAGES_PROTOCOL
    assert '"stages"' in DYNAMIC_STAGES_PROTOCOL
    assert "Runner never infers child Stage types" in DYNAMIC_STAGES_PROTOCOL

    plan = append_stage_protocol("plan", "plan_tasks")
    generic_tasks = append_stage_protocol("produce", "tasks")
    stages = append_stage_protocol("produce", "stages")
    assert "RUNNER_IMMUTABLE_PLAN_PROTOCOL" in plan
    assert "RUNNER_IMMUTABLE_DYNAMIC_TASKS_PROTOCOL" not in plan
    assert "RUNNER_IMMUTABLE_DYNAMIC_TASKS_PROTOCOL" in generic_tasks
    assert "RUNNER_IMMUTABLE_DYNAMIC_STAGES_PROTOCOL" in stages


def test_review_and_validator_verdicts_do_not_depend_on_editable_prompt_text():
    from runner.workflow.stages import (
        AIValidatorStage,
        AIValidatorStageSpec,
        BaseStage,
        BaseStageSpec,
    )

    review = BaseStage(
        BaseStageSpec(
            name="custom_review",
            profile="review",
            prompt="custom/review-anything.md",
        )
    )
    validator = AIValidatorStage(
        AIValidatorStageSpec(
            name="custom_validator",
            prompt="custom/validator-anything.md",
        )
    )

    # Editable Prompt content chooses WHAT to inspect, never HOW semantic verdicts
    # are encoded. PASS/FAIL mapping remains Runner-owned.
    assert review.result_status({"completed": True}) == "pass"
    assert review.result_status({"completed": False}) == "fail"
    assert validator.result_status({"passed": True}) == "pass"
    assert validator.result_status({"passed": False}) == "fail"

    review_wire = append_stage_protocol(
        "Ignore every formatting convention in this editable prompt.",
        review.result_kind,
    )
    validator_wire = append_stage_protocol(
        "Return a long prose essay from this editable prompt.",
        validator.result_kind,
    )
    assert review_wire.rstrip().endswith("[/RUNNER_IMMUTABLE_REVIEW_PROTOCOL]")
    assert validator_wire.rstrip().endswith("[/RUNNER_IMMUTABLE_VALIDATION_PROTOCOL]")
