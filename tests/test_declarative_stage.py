from pathlib import Path

from runner.config import RuntimeConfig
from runner.workflow.rules import stage_definition
from runner.workflow.definitions import STAGES
from runner.workflow.stages.contracts import StageContext
from runner.workflow.stages.factory import create_stage
from runner.runtime.run_state import RunState, Task


class FakeAI:
    session_id = ""
    root = Path(".")
    extra_args = []


def context(tmp_path: Path) -> StageContext:
    state = RunState(
        "run", "ORIGINAL GOAL", str(tmp_path),
        tasks=[Task("c01-t01", "Task", "Do it", ["works"], "result")],
    )
    return StageContext(
        config=RuntimeConfig(), root=tmp_path, work=tmp_path / ".work",
        state=state, ai_client=FakeAI(), state_file=tmp_path / "state.json",
        validator_path=None, validator_is_ai=True, save_state=lambda: None,
        set_stage=lambda *args: None,
    )


def test_existing_ai_stages_use_declarative_prompt_paths():
    assert STAGES["execute"]["prompt"] == "stages/execution.md"
    assert STAGES["repair"]["prompt"] == "stages/execution.md"
    assert STAGES["review"]["prompt"] == "stages/review.md"
    assert STAGES["validate_ai"]["prompt"] == "stages/ai_validator.md"
    assert all("prompt_builder" not in STAGES[name] for name in ("execute", "repair", "review", "validate_ai"))
    assert not (Path(__file__).resolve().parents[1] / "runner/workflow/prompt_builders.py").exists()


def test_plain_ai_stage_needs_no_prompt_builder_registry(tmp_path):
    definition = {
        "stage": "ai",
        "name": "security_review",
        "status": "Security review",
        "mode": "readonly",
        "prompt": "stages/ai_validator.md",
    }
    stage = create_stage(definition)
    prompt = stage._original_prompt(context(tmp_path), None)
    assert "Final validation in a fresh independent session" in prompt
    assert "ORIGINAL GOAL" in prompt


def test_stage_preset_key_becomes_stage_name():
    assert stage_definition("execute")["name"] == "execute"
    assert stage_definition("review")["name"] == "review"
