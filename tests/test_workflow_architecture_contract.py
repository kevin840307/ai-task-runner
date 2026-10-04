from __future__ import annotations

from pathlib import Path

from runner.workflow.registry import STAGE_REGISTRY, workflow_catalog


ROOT = Path(__file__).resolve().parents[1]
STAGES = ROOT / "runner" / "workflow" / "stages"
EXECUTION = ROOT / "runner" / "workflow" / "execution"


def test_builtin_special_stages_have_clear_one_file_ownership():
    assert not (STAGES / "core.py").exists()
    assert not (STAGES / "executor.py").exists()
    assert (STAGES / "base_stage.py").is_file()
    assert (STAGES / "plan_stage.py").is_file()
    assert (STAGES / "ai_validator_stage.py").is_file()
    assert (STAGES / "command_stage.py").is_file()
    assert (STAGES / "handoff_stage.py").is_file()
    assert (EXECUTION / "stage_executor.py").is_file()


def test_stage_executor_is_execution_policy_not_a_stage_type():
    source = (EXECUTION / "stage_executor.py").read_text(encoding="utf-8")
    assert "class StageExecutor" in source
    assert "Same Session" in source
    assert "Fresh Session" in source
    assert "is_transient_error" in source
    assert set(STAGE_REGISTRY) == {"base", "plan", "ai_validator", "command", "handoff"}


def test_removed_task_scope_contract_cannot_reappear():
    schema = (ROOT / "runner" / "workflow" / "schema.py").read_text(encoding="utf-8")
    state = (ROOT / "runner" / "runtime" / "run_state.py").read_text(encoding="utf-8")
    flow = (ROOT / "runner" / "workflow" / "flow_engine.py").read_text(encoding="utf-8")
    editor = (ROOT / "ui" / "studio-src" / "src" / "main.tsx").read_text(encoding="utf-8")

    forbidden = ("task_step", 'scope: task', '"scope"', "type: task", "type: review")
    for token in forbidden:
        assert token not in schema
        assert token not in state
        assert token not in flow
    assert "task_step" not in editor
    assert "Per task" not in editor
    assert "PER TASK" not in editor


def test_catalog_exposes_only_current_stage_model():
    catalog = workflow_catalog()
    assert set(catalog["stage_types"]) == {"base", "plan", "ai_validator", "command", "handoff"}
    assert "scope" not in catalog["node_options"]
    assert set(catalog["stage_types"]["base"]["profiles"]) == {"generic", "execute", "review"}
    assert catalog["stage_types"]["plan"]["dynamic_output"] is True


def test_structured_output_repair_cannot_rotate_sessions():
    structured = (ROOT / "runner" / "agent" / "structured.py").read_text(encoding="utf-8")
    base_stage = (STAGES / "base_stage.py").read_text(encoding="utf-8")

    assert "fresh_ask" not in structured
    assert "fresh_retries" not in structured
    assert "structured_fresh_retries" not in base_stage
    assert "_structured_fresh_ask" not in base_stage
    assert "structured_retries" in base_stage
    assert "StageExecutor" in structured
