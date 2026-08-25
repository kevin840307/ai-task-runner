from pathlib import Path

from runner.config import RuntimeConfig
from runner.runtime.run_state import RunState, Task
from runner.workflow.registry import STAGE_REGISTRY, create_stage, stage_definition
from runner.workflow.stages.contracts import StageContext


class FakeAI:
    session_id = ""
    root = Path(".")
    extra_args = []


def context(tmp_path: Path) -> StageContext:
    state = RunState(
        "run",
        "ORIGINAL GOAL",
        str(tmp_path),
        tasks=[Task("c01-t01", "Task", "Do it", ["works"], "result")],
    )
    return StageContext(
        config=RuntimeConfig(),
        root=tmp_path,
        work=tmp_path / ".work",
        state=state,
        ai_client=FakeAI(),
        state_file=tmp_path / "state.json",
        validator_path=None,
        validator_is_ai=True,
        save_state=lambda: None,
        set_stage=lambda *args: None,
    )


def test_existing_ai_stages_use_declarative_prompt_paths():
    defaults = {
        name: registration.defaults for name, registration in STAGE_REGISTRY.items()
    }
    assert defaults["execute"]["prompt"] == "stages/execution.md"
    assert defaults["repair"]["prompt"] == "stages/execution.md"
    assert defaults["task_review"]["prompt"] == "stages/review.md"
    assert defaults["ai"]["prompt"] == "stages/workflow_prompt.md"
    assert defaults["validate_ai"]["prompt"] == "stages/ai_validator.md"
    assert all("prompt_builder" not in defaults[name] for name in defaults)
    assert not (
        Path(__file__).resolve().parents[1] / "runner/workflow/prompt_builders.py"
    ).exists()


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
    assert "Final validation. This is a fresh independent read-only session." in prompt
    assert "ORIGINAL GOAL" in prompt


def test_stage_preset_key_becomes_stage_name():
    assert stage_definition("execute")["name"] == "execute"
    assert stage_definition("task_review")["name"] == "review"
