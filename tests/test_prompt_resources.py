from pathlib import Path

from runner.assets import PROMPT_DIR, WORKFLOW_DIR
from runner.prompting import PROMPT_ROOT
from runner.workflow.stages import PlanStageSpec

ROOT = Path(__file__).resolve().parents[1]


def test_prompt_assets_are_categorized_under_one_asset_package():
    assert PROMPT_ROOT == PROMPT_DIR
    common = {p.name for p in (PROMPT_DIR / "common").glob("*.md")}
    ralphy = {p.name for p in (PROMPT_DIR / "ralphy").glob("*.md")}
    workflow = {p.name for p in (PROMPT_DIR / "workflow").glob("*.md")}

    assert {
        "planning.md",
        "execution.md",
        "review.md",
        "ai_validator.md",
        "rules.md",
        "grill.md",
    } <= common
    assert ralphy == {"ralphy.md"}
    assert {"workflow_prompt.md", "workflow_review.md"} <= workflow
    assert not (ROOT / "runner" / "prompts").exists()


def test_workflow_assets_are_separate_from_prompt_assets():
    assert {p.name for p in WORKFLOW_DIR.glob("*.yaml")} >= {
        "ai.yaml",
        "file.yaml",
        "mixed.yaml",
        "ralphy_ai_validate.yaml",
    }
    assert not list(WORKFLOW_DIR.glob("*.md"))
    assert not list(PROMPT_DIR.glob("*.yaml"))


def test_setuptools_packages_only_current_runner_structure_and_assets():
    config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for package in (
        '"runner.agent"',
        '"runner.assets"',
        '"runner.plugins"',
        '"runner.runtime"',
        '"runner.workflow"',
        '"runner.workflow.stages"',
    ):
        assert package in config

    for removed in (
        '"runner.ai"',
        '"runner.backends"',
        '"runner.project"',
        '"runner.prompts"',
        '"runner.workflow.system"',
        '"runner.workflow.custom"',
    ):
        assert removed not in config

    assert '"runner.assets" = [' in config
    assert '"workflows/*.yaml"' in config
    assert '"prompts/common/*.md"' in config
    assert '"prompts/ralphy/*.md"' in config
    assert '"prompts/workflow/*.md"' in config


def test_plan_defaults_to_categorized_common_prompt():
    spec = PlanStageSpec(name="planning")
    assert spec.allow_project_read is True
    assert spec.prompt == "common/planning.md"

    planning = (PROMPT_DIR / spec.prompt).read_text(encoding="utf-8")
    assert "any readable path" in planning
    assert "outside the current Project" in planning
    assert "only when" in planning
    assert not (PROMPT_DIR / "common" / "planning_rules.md").exists()
    assert not (PROMPT_DIR / "common" / "plan_finalize.md").exists()


def test_prompt_runtime_is_one_module_not_a_parallel_prompt_package():
    assert (ROOT / "runner" / "prompting.py").is_file()
    assert not (ROOT / "runner" / "prompts").exists()
