from importlib.resources import files
from pathlib import Path

from runner.agent.prompts import render_prompt_template

ROOT = Path(__file__).resolve().parents[1]


def test_prompt_templates_are_packaged_resources():
    package_files = {
        item.name
        for item in files("runner.agent.prompt_templates").iterdir()
        if item.name.endswith(".md")
    }
    assert "planning_rules.md" in package_files
    assert "execution.md" in package_files
    assert "ai_validator.md" in package_files
    assert render_prompt_template("planning_rules.md", {"work": "work"})


def test_setuptools_includes_prompt_template_package_data():
    config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"runner.agent.prompt_templates",' in config
    assert '[tool.setuptools.package-data]' in config
    assert '"runner.agent.prompt_templates" = ["*.md"]' in config
    assert not (ROOT / "prompts").exists()
