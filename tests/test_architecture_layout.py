from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stage_ownership_is_inside_flow():
    assert not (ROOT / "runner/stages").exists()
    stages = ROOT / "runner/flow/stages"
    assert stages.is_dir()
    for name in ("base.py", "executor.py", "factory.py", "global_stage.py", "plan.py", "python_validation.py"):
        assert (stages / name).is_file()


def test_default_flow_is_data_only():
    source = (ROOT / "runner/flow/default.py").read_text(encoding="utf-8")
    assert "DEFAULT_FLOW" in source
    assert "STAGES" in source
    assert "def " not in source
