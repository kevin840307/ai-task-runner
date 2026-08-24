from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stage_ownership_is_inside_workflow():
    assert not (ROOT / "runner/stages").exists()
    stages = ROOT / "runner/workflow/stages"
    assert stages.is_dir()
    for name in ("contracts.py", "executor.py", "factory.py", "ai_stage.py", "plan_stage.py", "python_validator.py"):
        assert (stages / name).is_file()


def test_workflow_definitions_are_data_only():
    source = (ROOT / "runner/workflow/definitions.py").read_text(encoding="utf-8")
    assert "FLOWS" in source
    assert "STAGES" in source
    assert "def " not in source
