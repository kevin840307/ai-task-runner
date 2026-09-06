from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_all_prompt_templates_live_under_one_package():
    stage_files = {p.name for p in files("runner.prompts.stages").iterdir() if p.name.endswith(".md")}
    system_files = {p.name for p in files("runner.prompts.system").iterdir() if p.name.endswith(".md")}
    assert {"planning_rules.md", "execution.md", "ai_validator.md"} <= stage_files
    assert {"rules.md", "structured_output_retry.md"} <= system_files
    assert not (ROOT / "runner/workflow/prompts").exists()
    assert not (ROOT / "runner/ai/prompts").exists()
    assert (ROOT / "runner/prompts/context.py").is_file()
    assert (ROOT / "runner/prompts/loader.py").is_file()
    assert not (ROOT / "runner/utils/templates.py").exists()

def test_setuptools_packages_central_prompt_resources():
    config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"runner.prompts.stages" = ["*.md"]' in config
    assert '"runner.prompts.system" = ["*.md"]' in config
    assert '"runner.workflow.system"' in config
    assert '"runner.workflow.system" = ["*.yaml"]' in config
    assert '"runner.project"' in config


def test_plan_defaults_to_optional_readonly_filesystem_inspection():
    from runner.workflow.stages.plan_stage import PlanStageSpec

    assert PlanStageSpec(name="planning").allow_project_read is True
    root = Path(__file__).resolve().parents[1]
    rules = (root / "runner" / "prompts" / "stages" / "planning_rules.md").read_text(encoding="utf-8")
    fresh = (root / "runner" / "prompts" / "stages" / "plan_finalize.md").read_text(encoding="utf-8")
    same = (root / "runner" / "prompts" / "stages" / "plan_finalize_same_session.md").read_text(encoding="utf-8")
    assert "any readable path" in rules
    assert "outside the current Project" in rules
    assert "Do not use more tools" not in fresh
    assert "Do not use more tools" not in same
    assert "only when" in fresh
    assert "only when" in same
