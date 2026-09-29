from pathlib import Path

import yaml

from runner.prompts.protocols import PLAN_PROTOCOL, REVIEW_PROTOCOL
from runner.workflow.stages.plan_stage import PlanStageSpec

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "runner" / "assets" / "workflows"
PROMPTS = ROOT / "runner" / "assets" / "prompts"


def text(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def test_editable_workflows_and_prompts_have_separate_asset_roots():
    for name in ("rules.md", "planning.md", "execution.md", "review.md", "ai_validator.md"):
        assert (PROMPTS / name).is_file()
    assert not (ROOT / "runner" / "prompts" / "system").exists()
    assert not (ROOT / "runner" / "prompts" / "stages").exists()


def test_core_rules_keep_scope_small_and_evidence_driven():
    value = text("rules.md")
    assert "complex, cross-file, cross-module, or multi-project work" in value
    assert "independently verifiable steps" in value
    assert "smallest goal-relevant scope" in value
    assert "Add or update focused tests" in value
    assert "Diagnose root causes" in value
    assert "Never claim completion before verification" in value


def test_planning_prompt_and_protocol_bound_discovery_and_todo_size():
    value = text("planning.md")
    assert "A simple coherent change may be one TODO" in value
    assert "Complex work should be split" in value
    assert "independently executable and independently verifiable TODOs" in value
    assert "large or multi-project work" in value
    assert "small enough for a limited-context model" in value
    assert "responsibility, dependency, risk, or verification boundaries" in value
    assert "self-contained or greenfield task" in PLAN_PROTOCOL
    assert "do not repeat equivalent searches" in PLAN_PROTOCOL
    assert "focused test/verification work" in PLAN_PROTOCOL


def test_execution_prompt_prefers_small_complete_changes_and_targeted_checks():
    value = text("execution.md")
    assert "execute it incrementally" in value
    assert "Do not stop after a partial sub-change" in value
    assert "cheapest validation that provides adequate evidence" in value
    assert "broader validation only when the change or risk requires it" in value
    assert "never modified, bypassed, weakened, replaced, or hardcoded against" in value


def test_review_prompt_is_decisive_and_not_a_fresh_broad_review():
    value = text("review.md")
    assert "decide immediately" in value
    assert "Do not perform a fresh broad code review" in value
    assert "smallest coherent solution" in value
    assert "unnecessary abstraction" in value
    assert "not stylistic preferences" in value
    assert "Do not fail for style preferences" in REVIEW_PROTOCOL


def test_final_validator_is_requirement_driven_and_bounded():
    value = text("ai_validator.md")
    assert "cross-file, cross-module, and cross-project consistency" in value
    assert "large or multi-project repositories" in value
    assert "not exhaustive inspection of every unrelated file or project" in value
    assert "original Goal as authoritative" in value
    assert "avoid duplicate parallel implementations" in value
    assert "over-engineered designs not required by the Goal" in value
    assert "smallest clear implementation that remains maintainable" in value


def test_builtin_workflows_use_explicit_plan_execute_review_validator_nodes():
    expected = {
        "ai.yaml": ["planning", "execute", "review", "validate_ai"],
        "file.yaml": ["planning", "execute", "review", "validate_file"],
        "mixed.yaml": ["planning", "execute", "review", "validate_file", "validate_ai"],
    }
    for name, flow in expected.items():
        data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        assert data["flow"] == flow
        assert data["stages"]["execute"]["scope"] == "task"
        assert data["stages"]["review"]["scope"] == "task"
        assert data["stages"]["review"]["routes"]["fail"] == "execute"


def test_builtin_validation_edges_close_back_through_planning():
    ai = yaml.safe_load((WORKFLOWS / "ai.yaml").read_text(encoding="utf-8"))
    file = yaml.safe_load((WORKFLOWS / "file.yaml").read_text(encoding="utf-8"))
    mixed = yaml.safe_load((WORKFLOWS / "mixed.yaml").read_text(encoding="utf-8"))

    assert ai["stages"]["validate_ai"]["routes"]["fail"] == "planning"
    assert file["stages"]["validate_file"]["routes"]["fail"] == "planning"
    assert mixed["stages"]["validate_file"]["routes"]["fail"] == "planning"
    assert mixed["stages"]["validate_ai"]["routes"]["fail"] == "planning"


def test_final_ai_vote_contract_uses_independent_sessions():
    for name in ("ai.yaml", "mixed.yaml"):
        data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        stage = data["stages"]["validate_ai"]
        assert stage["fresh_session_each_run"] is True
        assert stage["runs"] == 3
        assert stage["required_passes"] == 2
        assert stage["ai_validator_yolo"] is True
        assert stage["readonly_safety"] == "observe"


def test_editable_prompt_word_budgets_stay_bounded():
    limits = {
        "rules.md": 260,
        "planning.md": 380,
        "execution.md": 440,
        "review.md": 180,
        "ai_validator.md": 340,
    }
    for name, maximum in limits.items():
        words = len(text(name).split())
        assert words <= maximum, f"{name} grew to {words} words (budget {maximum})"


def test_planning_has_one_editable_prompt_asset():
    assert PlanStageSpec(name="planning").prompt == "planning.md"
    assert not (PROMPTS / "planning_rules.md").exists()
    assert not (PROMPTS / "plan_finalize.md").exists()
