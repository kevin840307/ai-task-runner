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
