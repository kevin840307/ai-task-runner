from __future__ import annotations

from pathlib import Path

from runner.workflow.registry import STAGE_REGISTRY


ROOT = Path(__file__).resolve().parents[1]
STAGES = ROOT / "runner" / "workflow" / "stages"
EXECUTION = ROOT / "runner" / "workflow" / "execution"


def test_builtin_stage_modules_stay_one_concrete_stage_per_file():
    expected = {
        "base": "base_stage.py",
        "plan": "plan_stage.py",
        "ai_validator": "ai_validator_stage.py",
        "command": "command_stage.py",
        "handoff": "handoff_stage.py",
    }
    assert set(STAGE_REGISTRY) >= set(expected)

    for stage_type, filename in expected.items():
        stage_class = STAGE_REGISTRY[stage_type]
        module_file = Path(__import__(stage_class.__module__, fromlist=["x"]).__file__).name
        assert module_file == filename

    assert not (STAGES / "core.py").exists()


def test_stage_executor_is_workflow_execution_policy_not_stage_type():
    assert (EXECUTION / "stage_executor.py").is_file()
    assert not (STAGES / "executor.py").exists()
    assert not (STAGES / "stage_executor.py").exists()

    source = (EXECUTION / "stage_executor.py").read_text(encoding="utf-8")
    assert "class StageExecutor" in source
    assert "technical recovery" in source or "technical" in source
    assert "is_transient_error" in source
    assert "changed_project_files" in source


def test_registry_remains_plugin_extensible_without_plugin_specific_branches():
    source = (ROOT / "runner" / "workflow" / "registry.py").read_text(encoding="utf-8")

    assert "def register_stage" in source
    assert "discover_plugins()" in source
    assert "stage_class.spec_class" in source
    assert "STAGE_REGISTRY[stage_type]" in source
    assert "plugin_name ==" not in source



def test_shared_stage_contracts_are_workflow_owned_not_stage_implementation_owned():
    contracts = ROOT / "runner" / "workflow" / "contracts.py"
    assert contracts.is_file()
    assert not (STAGES / "contracts.py").exists()

    contract_source = contracts.read_text(encoding="utf-8")
    assert "class StageResult" in contract_source
    assert "class StageContext" in contract_source
    assert "class StageExecution" in contract_source
    assert "class Stage(Protocol)" in contract_source

    executor_source = (EXECUTION / "stage_executor.py").read_text(encoding="utf-8")
    assert "from ..contracts import" in executor_source
    assert "stages.base_stage import" not in executor_source

    command_source = (STAGES / "command_stage.py").read_text(encoding="utf-8")
    assert "from ..contracts import" in command_source
    assert "BaseStage" not in command_source



def test_removed_structured_fresh_retry_contract_stays_absent():
    validator_source = (STAGES / "ai_validator_stage.py").read_text(encoding="utf-8")
    studio_source = (
        ROOT / "ui" / "studio-src" / "src" / "main.tsx"
    ).read_text(encoding="utf-8")

    assert "structured_fresh_retries" not in validator_source
    assert "structured_fresh_retries" not in studio_source


def test_stage_backend_model_selection_stays_backend_registry_driven():
    base_stage = (STAGES / "base_stage.py").read_text(encoding="utf-8")
    registry = (ROOT / "runner" / "workflow" / "registry.py").read_text(encoding="utf-8")
    studio = (ROOT / "ui" / "studio-src" / "src" / "main.tsx").read_text(encoding="utf-8")

    assert "backend_names()" in base_stage
    assert 'item.name == "backend"' in registry
    assert "backend_names()" in registry
    for source in (base_stage, studio):
        assert 'backend == "qwen"' not in source
        assert 'backend == "opencode"' not in source
        assert '["qwen", "opencode"]' not in source
        assert "['qwen', 'opencode']" not in source


def test_flow_and_executor_responsibility_boundaries_stay_separate():
    flow_source = (ROOT / "runner" / "workflow" / "flow_engine.py").read_text(encoding="utf-8")
    executor_source = (EXECUTION / "stage_executor.py").read_text(encoding="utf-8")

    for token in (
        "sleep_with_heartbeat",
        "is_transient_error",
        "reset_session(",
        "retry_mode",
    ):
        assert token not in flow_source

    for token in (
        "resolve_stage_target",
        "resolve_handoff_target",
        "workflow_position",
        "max_cycles",
    ):
        assert token not in executor_source


def test_stage_backend_override_does_not_inherit_other_backend_model():
    client = (ROOT / "runner" / "agent" / "client.py").read_text(encoding="utf-8")
    assert "inherited_model" not in client
    assert 'effective_model = str(model_override or "").strip()' in client
