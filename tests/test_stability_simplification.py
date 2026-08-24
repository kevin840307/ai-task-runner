from pathlib import Path


def test_flow_is_plain_data_and_pipeline_is_generic():
    root = Path(__file__).resolve().parents[1]
    default = (root / "runner/flow/default.py").read_text(encoding="utf-8")
    pipeline = (root / "runner/flow/pipeline.py").read_text(encoding="utf-8")
    factory = (root / "runner/flow/stages/factory.py").read_text(encoding="utf-8")

    assert "FLOWS = {" in default
    assert '"default": [' in default
    assert "STAGES = {" in default
    assert "def " not in default
    assert "create_stage(item)" in pipeline
    assert "STAGE_REGISTRY" in factory
    assert '"defaults":' in factory
    for business_name in ("understand", "execute", "review", "repair", "validate"):
        assert business_name not in pipeline


def test_stage_executor_remains_shared_execution_boundary():
    root = Path(__file__).resolve().parents[1]
    executor = (root / "runner/flow/stages/executor.py").read_text(encoding="utf-8")
    assert "class StageExecutor" in executor
    assert "self.hooks.before(action)" in executor
    assert "self.hooks.after(action, tokens)" in executor
    assert "same_failures" in executor
    assert "fresh_session_round" in executor
