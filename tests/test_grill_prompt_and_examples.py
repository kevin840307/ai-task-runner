from pathlib import Path

from runner.prompting import append_stage_protocol, prompt_variables, render_prompt
from runner.workflow.loader import load_workflow
from runner.workflow.registry import STAGE_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
GRILL_PROMPT = ROOT / "runner" / "assets" / "prompts" / "common" / "grill.md"
EXAMPLES = ROOT / "tool" / "workflow"


def test_grill_reuses_review_stage_and_common_prompt_asset():
    assert "grill" not in STAGE_REGISTRY
    assert GRILL_PROMPT.is_file()
    variables = prompt_variables(str(GRILL_PROMPT))
    assert {"always_instructions", "goal", "task"} <= variables
    text = render_prompt(
        str(GRILL_PROMPT),
        {
            "always_instructions": "",
            "goal": "Keep API retry durable.",
            "task": None,
        },
    )
    assert "Keep API retry durable." in text
    wire = append_stage_protocol(text, "review")
    assert '"completed":false' in wire
    assert '"completed":true' in wire


def test_all_existing_tool_workflow_examples_load():
    files = sorted(EXAMPLES.glob("*.yaml"))
    assert files
    for path in files:
        assert load_workflow(path), path.name


def test_grill_examples_use_review_stage_and_result_edges():
    for name in (
        "02_ai_with_grill.yaml",
        "04_mixed_with_grill.yaml",
        "05_grill_vote_3_choose_2.yaml",
    ):
        workflow = load_workflow(EXAMPLES / name)
        grill = next(stage for stage in workflow if stage["name"] == "grill")
        assert grill["type"] == "review"
        assert grill["fresh_session_on_start"] is True
        assert "retry" not in grill
        assert "recover" not in grill
        assert grill["routes"]["fail"] == "planning"
        assert Path(grill["prompt"]).resolve() == GRILL_PROMPT.resolve()
