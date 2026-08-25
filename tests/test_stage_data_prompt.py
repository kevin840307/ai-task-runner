from pathlib import Path
from types import SimpleNamespace

from runner.workflow.stages.contracts import StageContext
from runner.workflow.stages.base_stage import BaseStage, BaseStageSpec
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
        name="security_review", status="checking", prompt="stages/ai_validator.md"
    ))
    rendered = stage._original_prompt(ctx, None)
    assert "Final validation" in rendered


def test_default_flow_has_no_prompt_path_resolver_hardcode():
    source = Path("runner/workflow/stages/base_stage.py").read_text(encoding="utf-8")
    assert '"stages/" +' not in source
    assert '.replace(".md"' not in source
