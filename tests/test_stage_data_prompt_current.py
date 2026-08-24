from pathlib import Path
from types import SimpleNamespace

from runner.flow.stages.base import StageContext
from runner.flow.stages.global_stage import GlobalStage, GlobalStageSpec
from runner.runtime.state import RunState


def test_plain_ai_stage_can_reference_bundled_prompt_path_directly(tmp_path):
    state = RunState(run_id="test", goal="check project", project_root=str(tmp_path))
    ctx = StageContext(
        args=SimpleNamespace(), root=tmp_path, work=tmp_path, state=state,
        model=SimpleNamespace(session_id=""), state_file=tmp_path / "state.json",
        validator=None, ai_validation=False, save_state=lambda: None,
        set_stage=lambda *_: None,
    )
    stage = GlobalStage(GlobalStageSpec(
        name="security_review", status="checking", prompt="stages/ai_validator.md"
    ))
    rendered = stage._original_prompt(ctx, None)
    assert "Final validation" in rendered


def test_default_flow_has_no_prompt_path_resolver_hardcode():
    source = Path("runner/flow/stages/global_stage.py").read_text(encoding="utf-8")
    assert '"stages/" +' not in source
    assert '.replace(".md"' not in source
