from pathlib import Path
from types import SimpleNamespace

from runner.workflow.stages import BaseStage, BaseStageSpec, StageContext
from runner.runtime.run_state import RunState


def test_plain_base_stage_can_reference_bundled_prompt_path_directly(tmp_path):
    state = RunState(run_id="test", goal="check project", project_root=str(tmp_path))
    ctx = StageContext(
        config=SimpleNamespace(), root=tmp_path, work=tmp_path, state=state,
        ai_client=SimpleNamespace(session_id=""), state_file=tmp_path / "state.json",
        validator_path=None, validator_is_ai=False, save_state=lambda: None,
        set_stage=lambda *_: None,
    )
    stage = BaseStage(BaseStageSpec(
        name="security_review", status="checking", prompt="common/ai_validator.md"
    ))
    rendered = stage._original_prompt(ctx, None)
    assert "Final validation" in rendered


def test_default_flow_has_no_prompt_path_resolver_hardcode():
    source = Path("runner/workflow/stages/base_stage.py").read_text(encoding="utf-8")
    assert '"stages/" +' not in source
    assert '.replace(".md"' not in source


def test_previous_structured_data_is_available_and_bounded(tmp_path):
    import json

    from runner.prompting import PREVIOUS_DATA_CHARS, build_stage_prompt_context
    from runner.workflow.stages import StageResult

    state = RunState(run_id="test", goal="check project", project_root=str(tmp_path))
    ctx = StageContext(
        config=SimpleNamespace(), root=tmp_path, work=tmp_path, state=state,
        ai_client=SimpleNamespace(session_id=""), state_file=tmp_path / "state.json",
        validator_path=None, validator_is_ai=False, save_state=lambda: None,
        set_stage=lambda *_: None,
    )
    previous = StageResult(
        "review",
        "fail",
        data={
            "completed": False,
            "reason": "Missing required evidence",
            "missing_items": [f"missing-{index}-" + "x" * 900 for index in range(30)],
        },
    )

    data = build_stage_prompt_context(ctx, "repair", previous)["previous"]["data"]

    assert data["completed"] is False
    assert data["reason"] == "Missing required evidence"
    assert data["missing_items"][0].startswith("missing-0-")
    assert len(json.dumps(data, ensure_ascii=False)) <= PREVIOUS_DATA_CHARS + 32


def test_top_level_review_failure_feedback_uses_structured_data_when_output_empty(tmp_path):
    from types import SimpleNamespace

    from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec
    from runner.workflow.stages import StageResult

    state = RunState(run_id="test", goal="check project", project_root=str(tmp_path))
    ctx = StageContext(
        config=SimpleNamespace(),
        root=tmp_path,
        work=tmp_path,
        state=state,
        ai_client=SimpleNamespace(session_id="session"),
        state_file=tmp_path / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda *_: None,
    )
    stage = BaseStage(BaseStageSpec(name="execute", prompt="common/execution.md"))
    previous = StageResult(
        "review",
        "fail",
        output="",
        data={
            "completed": False,
            "reason": "Required line is missing",
            "missing_items": ["Add REVIEW_REQUIRED"],
        },
        kind="review",
    )

    feedback = stage._control_feedback(ctx, previous)

    assert "Review: Required line is missing" in feedback
    assert 'Review missing_items: ["Add REVIEW_REQUIRED"]' in feedback


def test_top_level_validator_failure_feedback_uses_structured_data_when_output_empty(tmp_path):
    from types import SimpleNamespace

    from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec
    from runner.workflow.stages import StageResult

    state = RunState(run_id="test", goal="check project", project_root=str(tmp_path))
    ctx = StageContext(
        config=SimpleNamespace(),
        root=tmp_path,
        work=tmp_path,
        state=state,
        ai_client=SimpleNamespace(session_id="session"),
        state_file=tmp_path / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda *_: None,
    )
    stage = BaseStage(BaseStageSpec(name="execute", prompt="common/execution.md"))
    previous = StageResult(
        "validate_ai",
        "fail",
        output="",
        data={
            "passed": False,
            "reason": "Validation evidence is incomplete",
            "missing_items": ["Run the required check"],
        },
        kind="validation",
    )

    feedback = stage._control_feedback(ctx, previous)

    assert "Validator: Validation evidence is incomplete" in feedback
    assert 'Validator missing_items: ["Run the required check"]' in feedback
