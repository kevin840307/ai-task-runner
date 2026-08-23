from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_obsolete_top_level_feature_modules_are_absent():
    obsolete = {
        "core.py",
        "models.py",
        "state_store.py",
        "process_control.py",
        "ui.py",
        "defaults.py",
        "value_checks.py",
        "agent_args.py",
        "agent_factory.py",
        "ai_validation.py",
        "debug.py",
        "file_validation.py",
        "git_guard.py",
        "model_call.py",
        "model_results.py",
        "planning.py",
        "policy.py",
        "project_guard.py",
        "prompting.py",
        "reviewing.py",
        "support.py",
        "validation.py",
    }
    assert not {path.name for path in (ROOT / "runner").glob("*.py")} & obsolete


def test_internal_modules_use_feature_owners_directly():
    core = (ROOT / "runner" / "engine" / "core.py").read_text(encoding="utf-8")
    planning = (ROOT / "runner" / "workflow" / "planning.py").read_text(
        encoding="utf-8"
    )
    reviewing = (ROOT / "runner" / "workflow" / "reviewing.py").read_text(
        encoding="utf-8"
    )
    file_validation = (
        ROOT / "runner" / "workflow" / "validation" / "file.py"
    ).read_text(encoding="utf-8")

    assert "from ..agent.factory import AgentFactory" in core
    assert "from ..workflow.planning import build_plan" in core
    assert "from ..workflow.reviewing import review_task" in core
    assert "from ..safety.project_guard import (" in core
    assert "from ..agent.calls import" in planning
    assert "from ..safety.project_guard import readonly_ask" in planning
    assert "from .structured import readonly_structured_call" in reviewing
    assert "from ...runtime.process_control import run_process" in file_validation


def test_feature_packages_expose_canonical_modules():
    from runner.agent import arguments, prompts, results
    from runner.safety import git_guard, policy, project_guard
    from runner.workflow import planning, reviewing
    from runner.workflow.validation import ai, file

    assert arguments.planning_agent_args.__module__ == "runner.agent.arguments"
    assert prompts.execution_prompt.__module__ == "runner.agent.prompts"
    assert results.parse_tasks.__module__ == "runner.agent.results"
    assert planning.build_plan.__module__ == "runner.workflow.planning"
    assert reviewing.review_task.__module__ == "runner.workflow.reviewing"
    assert ai.run_ai_validator.__module__ == "runner.workflow.validation.ai"
    assert file.run_file_validator.__module__ == "runner.workflow.validation.file"
    assert policy.protected_paths.__module__ == "runner.safety.policy"
    assert project_guard.snapshot.__module__ == "runner.safety.project_guard"
    assert git_guard.git_subcommand.__module__ == "runner.safety.git_guard"
