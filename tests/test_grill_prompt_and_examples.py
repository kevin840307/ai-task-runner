from pathlib import Path

from runner.prompts.loader import prompt_variables, render_prompt
from runner.prompts.protocols import append_stage_protocol
from runner.workflow.loader import load_workflow
from runner.workflow.registry import STAGE_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
GRILL_PROMPT = ROOT / "runner" / "prompts" / "stages" / "grill.md"
EXAMPLES = ROOT / "tool" / "workflow"


def test_grill_reuses_review_stage_and_contract() -> None:
    assert "grill" not in STAGE_REGISTRY
    assert GRILL_PROMPT.is_file()
    variables = prompt_variables(str(GRILL_PROMPT))
    assert {"always_instructions", "goal", "task"} <= variables
    assert "previous" not in variables
    text = render_prompt(
        str(GRILL_PROMPT),
        {
            "always_instructions": "",
            "goal": "Keep API retry durable.",
            "task": None,
        },
    )
    assert "Keep API retry durable." in text
    assert "current implementation" in text
    wire_prompt = append_stage_protocol(text, "review")
    assert '"completed":false' in wire_prompt
    assert '"completed":true' in wire_prompt


def test_all_tool_workflow_examples_load() -> None:
    files = sorted(EXAMPLES.glob("*.yaml"))
    assert len(files) >= 7
    for path in files:
        workflow = load_workflow(path)
        assert workflow, path.name


def test_grill_examples_use_review_stage_and_fresh_session() -> None:
    for name in (
        "02_ai_with_grill.yaml",
        "04_mixed_with_grill.yaml",
        "05_grill_vote_3_choose_2.yaml",
    ):
        workflow = load_workflow(EXAMPLES / name)
        grill = next(stage for stage in workflow if stage["name"] == "grill")
        assert grill["type"] == "review"
        assert grill["fresh_session_on_start"] is True
        assert grill["retry"] == 0
        assert Path(grill["prompt"]).resolve() == GRILL_PROMPT.resolve()
