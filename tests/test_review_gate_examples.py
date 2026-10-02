from pathlib import Path

from runner.workflow.loader import load_workflow
from runner.workflow.registry import STAGE_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "tool" / "workflow"


def test_review_gate_examples_use_current_review_stage_contract():
    assert "grill" not in STAGE_REGISTRY
    for name, stage_name in (
        ("02_ai_with_review_gate.yaml", "challenge_review"),
        ("04_mixed_with_review_gate.yaml", "challenge_review"),
        ("05_review_vote_3_choose_2.yaml", "review_vote"),
    ):
        workflow = load_workflow(EXAMPLES / name)
        stage = next(item for item in workflow if item["name"] == stage_name)
        assert stage["type"] == "base"
        assert stage["profile"] == "review"
        assert stage["session_policy"] == "fresh"
        assert stage["routes"]["fail"] == "planning"
        assert "recover" not in stage
        assert "restart_at" not in stage
        assert "fresh_session_on_start" not in stage


def test_all_current_tool_workflow_examples_load():
    files = sorted(EXAMPLES.glob("*.yaml"))
    assert files
    for path in files:
        assert load_workflow(path), path.name


def test_obsolete_grill_prompt_and_tool_examples_are_absent():
    assert not (ROOT / "runner" / "assets" / "prompts" / "common" / "grill.md").exists()
    for name in (
        "02_ai_with_grill.yaml",
        "04_mixed_with_grill.yaml",
        "05_grill_vote_3_choose_2.yaml",
    ):
        assert not (EXAMPLES / name).exists()
