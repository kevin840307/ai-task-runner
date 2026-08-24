from pathlib import Path

from runner.config import RuntimeConfig
from runner.flow.behavior import _stage
from runner.flow.default import STAGES
from runner.flow.prompts import PROMPT_BUILDERS
from runner.flow.stages.base import StageContext
from runner.flow.stages.factory import create_stage
from runner.runtime.state import RunState, Task


class Model:
    session_id = ""
    root = Path(".")
    extra_args = []


def context(tmp_path: Path) -> StageContext:
    state = RunState(
        "run", "ORIGINAL GOAL", str(tmp_path),
        tasks=[Task("c01-t01", "Task", "Do it", ["works"], "result")],
    )
    return StageContext(
        args=RuntimeConfig(), root=tmp_path, work=tmp_path / ".work",
        state=state, model=Model(), state_file=tmp_path / "state.json",
        validator=None, ai_validation=True, save_state=lambda: None,
        set_stage=lambda *args: None,
    )


def test_existing_ai_stages_use_declarative_prompt_paths():
    assert STAGES["execute"]["prompt"] == "stages/execution.md"
    assert STAGES["repair"]["prompt"] == "stages/execution.md"
    assert STAGES["validate_ai"]["prompt"] == "stages/ai_validator.md"
    assert all("prompt_builder" not in STAGES[name] for name in ("execute", "repair", "validate_ai"))


def test_plain_ai_stage_needs_no_prompt_builder_registry(tmp_path):
    definition = {
        "stage": "global",
        "name": "security_review",
        "status": "Security review",
        "mode": "readonly",
        "prompt": "stages/ai_validator.md",
    }
    assert "security_review" not in PROMPT_BUILDERS
    stage = create_stage(definition)
    prompt = stage._original_prompt(context(tmp_path), None)
    assert "Final validation in a fresh independent session" in prompt
    assert "ORIGINAL GOAL" in prompt


def test_stage_preset_key_becomes_stage_name():
    assert _stage("execute")["name"] == "execute"
    assert _stage("review")["name"] == "review"
