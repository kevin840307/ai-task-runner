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


def test_sandbox_prompt_context_hides_host_root_and_uses_relative_validator(tmp_path):
    from runner.prompting import build_stage_prompt_context

    validator = tmp_path / "validation.py"
    validator.write_text("print('ok')\n", encoding="utf-8")
    state = RunState(run_id="test", goal="check project", project_root=str(tmp_path))
    ctx = StageContext(
        config=SimpleNamespace(
            sandbox=True,
            validator_prompt="",
            ai_validator_prompt="",
        ),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=SimpleNamespace(session_id=""),
        state_file=tmp_path / ".work" / "state.json",
        validator_path=validator,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda *_: None,
    )

    values = build_stage_prompt_context(ctx, "execute")

    assert values["project"]["root"] == "."
    assert values["validation"]["validator_path"] == "validation.py"
    assert str(tmp_path.resolve()) not in values["rules"]
    assert "WRITE/CREATE/DELETE only inside project root: ." in values["rules"]


def test_non_sandbox_prompt_context_keeps_host_paths(tmp_path):
    from runner.prompting import build_stage_prompt_context

    validator = tmp_path / "validation.py"
    state = RunState(run_id="test", goal="check project", project_root=str(tmp_path))
    ctx = StageContext(
        config=SimpleNamespace(
            sandbox=False,
            validator_prompt="",
            ai_validator_prompt="",
        ),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=SimpleNamespace(session_id=""),
        state_file=tmp_path / ".work" / "state.json",
        validator_path=validator,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda *_: None,
    )

    values = build_stage_prompt_context(ctx, "execute")

    assert values["project"]["root"] == str(tmp_path)
    assert values["validation"]["validator_path"] == str(validator)
    assert str(tmp_path) in values["rules"]


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

    data = build_stage_prompt_context(ctx, "execute", previous)["previous"]["data"]

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


def test_current_review_feedback_is_not_duplicated_from_task_history(tmp_path):
    from types import SimpleNamespace

    from runner.runtime.run_state import Task
    from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec
    from runner.workflow.stages import StageResult

    task = Task(
        id="task-1",
        title="task",
        description="work",
        deliverable="artifact",
        acceptance_criteria=["done"],
        last_review={
            "completed": False,
            "reason": "stale review reason",
            "missing_items": ["stale item"],
        },
    )
    state = RunState(
        run_id="test",
        goal="check project",
        project_root=str(tmp_path),
        tasks=[task],
    )
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
            "reason": "current review reason",
            "missing_items": ["current item"],
        },
        kind="review",
    )

    feedback = stage._control_feedback(ctx, previous)

    assert feedback.count("Review: current review reason") == 1
    assert feedback.count('Review missing_items: ["current item"]') == 1
    assert "stale review reason" not in feedback
    assert "stale item" not in feedback


def test_task_local_review_retry_ignores_stale_run_validator_feedback(tmp_path):
    from types import SimpleNamespace

    from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec
    from runner.workflow.stages import StageResult

    state = RunState(run_id="test", goal="check project", project_root=str(tmp_path))
    state.validator_output = "VALIDATION_FAILED: stale README.md missing"
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
            "reason": "Current review needs one task-local fix",
            "missing_items": ["current item"],
        },
        kind="review",
    )

    feedback = stage._control_feedback(ctx, previous)

    assert "Current review needs one task-local fix" in feedback
    assert "stale README.md missing" not in feedback


def test_command_validator_failure_feedback_uses_current_transition_output(tmp_path):
    from types import SimpleNamespace

    from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec
    from runner.workflow.stages import StageResult

    state = RunState(run_id="test", goal="check project", project_root=str(tmp_path))
    state.validator_output = "VALIDATION_FAILED: stale old result"
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
    stage = BaseStage(BaseStageSpec(name="planning", prompt="common/planning.md"))
    previous = StageResult(
        "validate_file",
        "fail",
        output="VALIDATION_FAILED: replace route.txt content with exactly RECOVERED",
        data=None,
        kind="validation",
    )

    feedback = stage._control_feedback(ctx, previous)

    assert "Validator: VALIDATION_FAILED: replace route.txt content with exactly RECOVERED" in feedback
    assert "stale old result" not in feedback
    assert "validate_file:" not in feedback


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


def test_handoff_protocol_is_appended_on_same_session_continuation(tmp_path):
    from types import SimpleNamespace

    from runner.config.runtime import RuntimeConfig
    from runner.workflow.stages import HandoffStage, HandoffStageSpec, StageResult

    state = RunState(run_id="test", goal="route work", project_root=str(tmp_path))
    client = SimpleNamespace(session_id="router-session")
    ctx = StageContext(
        config=RuntimeConfig(goal="route work", project_root=str(tmp_path)),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=client,
        state_file=tmp_path / ".work" / "state.json",
        validator_path=None,
        validator_is_ai=False,
        save_state=lambda: None,
        set_stage=lambda *_: None,
    )
    stage = HandoffStage(HandoffStageSpec(
        name="coordinator",
        targets=["worker", "final_validate"],
        session_policy="main",
    ))

    first = stage._prompt(ctx, None, client)
    assert "[RUNNER_IMMUTABLE_HANDOFF_PROTOCOL]" in first
    assert "Allowed targets: worker, final_validate" in first

    stage._remember_prompt(ctx, client)
    second = stage._prompt(
        ctx,
        StageResult("worker", "pass", output="worker complete"),
        client,
    )

    assert second.startswith("RUNNER_SHARED_STAGE_CONTROL")
    assert "[RUNNER_IMMUTABLE_HANDOFF_PROTOCOL]" in second
    assert "Allowed targets: worker, final_validate" in second
    assert '{"target":"stage_name","reason":"concise reason"}' in second
