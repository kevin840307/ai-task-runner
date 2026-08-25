from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stage_ownership_is_inside_workflow():
    assert not (ROOT / "runner/stages").exists()
    stages = ROOT / "runner/workflow/stages"
    assert stages.is_dir()
    for name in (
        "contracts.py",
        "executor.py",
        "ai_stage.py",
        "plan_stage.py",
        "python_validator.py",
    ):
        assert (stages / name).is_file()
    assert not (stages / "factory.py").exists()


def test_workflow_has_one_stage_registry():
    assert not (ROOT / "runner/workflow/definitions.py").exists()
    source = (ROOT / "runner/workflow/registry.py").read_text(encoding="utf-8")
    assert "class StageRegistration" in source
    assert "def register_stage" in source
    assert "STAGE_REGISTRY" in source
