from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "runner" / "prompts" / "system"
STAGES = ROOT / "runner" / "prompts" / "stages"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_core_rules_cover_decomposition_large_projects_tests_and_evidence():
    text = _text(SYSTEM / "rules.md")
    assert "complex, cross-file, cross-module, or multi-project work" in text
    assert "independently verifiable steps" in text
    assert "large repositories" in text
    assert "smallest goal-relevant scope" in text
    assert "Add or update focused tests" in text
    assert "Diagnose root causes" in text
    assert "Never claim completion before verification" in text


def test_planner_splits_complex_work_without_overplanning_simple_work():
    rules = _text(STAGES / "planning_rules.md")
    from runner.prompts.protocols import PLAN_PROTOCOL
    assert "A simple coherent change may be one TODO" in rules
    assert "Complex work should be split" in rules
    assert "independently executable and independently verifiable TODOs" in rules
    assert "large or multi-project work" in rules
    assert "entry points, dependencies, contracts, and cross-project hops" in rules
    assert "small enough for a limited-context model" in rules
    assert "responsibility, dependency, risk, or verification boundaries" in rules
    assert "focused test/verification work" in PLAN_PROTOCOL


def test_execution_is_incremental_and_test_aware():
    text = _text(STAGES / "execution.md")
    assert "execute it incrementally" in text
    assert "verify an important intermediate result" in text
    assert "Add or update focused tests" in text
    assert "reproducible bug" in text
    assert "Diagnose the root cause" in text
    assert "never modified, bypassed, weakened, replaced, or hardcoded against" in text


def test_final_validator_scales_to_multi_project_without_exhaustive_scan():
    text = _text(STAGES / "ai_validator.md")
    assert "cross-file, cross-module, and cross-project consistency" in text
    assert "large or multi-project repositories" in text
    assert "not exhaustive inspection of every unrelated file or project" in text
    assert "original Goal as authoritative" in text


def test_system_workflow_topology_was_not_changed_by_prompt_optimization():
    expected_flows = {
        "ai.yaml": ["planning", "validate_ai"],
        "file.yaml": ["planning", "validate_file"],
        "mixed.yaml": ["planning", "validate_file", "validate_ai"],
    }
    import yaml

    for filename, expected in expected_flows.items():
        data = yaml.safe_load((ROOT / "runner" / "workflow" / "system" / filename).read_text(encoding="utf-8"))
        assert data["flow"] == expected


def test_converged_prompts_control_scope_and_validation_cost():
    core = _text(SYSTEM / "rules.md")
    execution = _text(STAGES / "execution.md")
    from runner.prompts.protocols import REVIEW_PROTOCOL
    validator = _text(STAGES / "ai_validator.md")
    assert "Do not perform unrelated cleanup" in core
    assert "cheapest validation that provides adequate evidence" in execution
    assert "broader validation only when the change or risk requires it" in execution
    assert "Do not fail for style preferences" in REVIEW_PROTOCOL
    assert "PASS requires adequate evidence" in validator
    assert "not exhaustive inspection" in validator


def test_converged_planner_uses_meaningful_boundaries_and_limited_context_todos():
    rules = _text(STAGES / "planning_rules.md")
    from runner.prompts.protocols import PLAN_PROTOCOL
    assert "responsibility, dependency, risk, or verification boundaries" in rules
    assert "limited-context model" in rules
    assert "never mechanically by file count" in rules
    assert "focused test creation/update" in rules
    assert "umbrella TODO" in PLAN_PROTOCOL


def test_system_workflow_stages_are_explicit_without_changing_flow():
    import yaml

    root = ROOT / "runner" / "workflow" / "system"
    ai = yaml.safe_load((root / "ai.yaml").read_text(encoding="utf-8"))
    file = yaml.safe_load((root / "file.yaml").read_text(encoding="utf-8"))
    mixed = yaml.safe_load((root / "mixed.yaml").read_text(encoding="utf-8"))

    assert ai["flow"] == ["planning", "validate_ai"]
    assert file["flow"] == ["planning", "validate_file"]
    assert mixed["flow"] == ["planning", "validate_file", "validate_ai"]
    assert ai["stages"]["validate_ai"]["fresh_session_each_run"] is True
    assert mixed["stages"]["validate_ai"]["fresh_session_each_run"] is True
    assert file["stages"]["validate_file"]["status"] == "正在執行 Python Validator"

def test_plan_protocol_bounds_greenfield_and_repeated_discovery():
    from runner.prompts.protocols import PLAN_PROTOCOL
    assert "self-contained or greenfield task" in PLAN_PROTOCOL
    assert "stop discovery and produce the plan immediately" in PLAN_PROTOCOL
    assert "do not repeat equivalent searches" in PLAN_PROTOCOL
    assert "smallest goal-relevant entry point" in PLAN_PROTOCOL



def test_small_model_prompts_have_explicit_stop_rules():
    core = _text(SYSTEM / "rules.md")
    planning = _text(STAGES / "planning_rules.md")
    execution = _text(STAGES / "execution.md")
    validator = _text(STAGES / "ai_validator.md")
    assert "stop exploring" in core
    assert "stop discovery" in planning
    assert "stop exploring" in execution
    assert "stop exploring" in validator


def test_editable_prompt_word_budgets_stay_bounded_for_small_models():
    limits = {
        SYSTEM / "rules.md": 260,
        STAGES / "planning_rules.md": 280,
        STAGES / "execution.md": 440,
        STAGES / "review.md": 170,
        STAGES / "ai_validator.md": 300,
    }
    for path, maximum in limits.items():
        words = len(_text(path).split())
        assert words <= maximum, f"{path.name} grew to {words} words (budget {maximum})"
