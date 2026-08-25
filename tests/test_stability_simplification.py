from pathlib import Path


def test_flow_is_plain_data_and_pipeline_is_generic():
    root = Path(__file__).resolve().parents[1]
    registry = (root / "runner/workflow/registry.py").read_text(encoding="utf-8")
    rules = (root / "runner/workflow/rules.py").read_text(encoding="utf-8")
    pipeline = (root / "runner/workflow/pipeline.py").read_text(encoding="utf-8")

    assert "INTERNAL_FLOWS = {" in rules
    assert "class StageRegistration" in registry
    assert "def register_stage" in registry
    assert "create_stage(item)" in pipeline
    assert "from .registry import create_stage" in pipeline
    assert not (root / "runner/workflow/stages/factory.py").exists()
    for business_name in ("understand", "execute", "review", "repair", "validate"):
        assert business_name not in pipeline


def test_stage_executor_remains_shared_execution_boundary():
    root = Path(__file__).resolve().parents[1]
    executor = (root / "runner/workflow/stages/executor.py").read_text(encoding="utf-8")
    assert "class StageExecutor" in executor
    assert "self.hooks.before(action)" in executor
    assert "self.hooks.after(action, tokens)" in executor
    assert "same_failures" in executor
    assert "fresh_session_round" in executor
