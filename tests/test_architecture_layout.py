from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_obsolete_top_level_feature_modules_are_absent():
    obsolete = {
        "core.py", "models.py", "state_store.py", "process_control.py", "ui.py",
        "defaults.py", "value_checks.py", "agent_args.py", "agent_factory.py",
        "ai_validation.py", "debug.py", "file_validation.py", "git_guard.py",
        "model_call.py", "model_results.py", "planning.py", "policy.py",
        "project_guard.py", "prompting.py", "reviewing.py", "support.py", "validation.py",
    }
    assert not {path.name for path in (ROOT / "runner").glob("*.py")} & obsolete


def test_core_uses_graph_and_stage_blocks_without_concrete_extensions():
    core = (ROOT / "runner/engine/core.py").read_text(encoding="utf-8")
    assert "from ..workflow.flow import default_flow" in core
    assert "from ..workflow.stages import" in core
    assert "AgentFactory" not in core
    assert "runner.safety" not in core
    assert "extensions.safety" not in core
    assert "LiveUI" not in core


def test_feature_packages_expose_canonical_modules():
    from runner.agent import prompts, results
    from runner.config import project_policy
    from runner.workflow import planning, reviewing
    from runner.workflow.validation import ai, file

    assert prompts.execution_prompt.__module__ == "runner.agent.prompts"
    assert results.parse_tasks.__module__ == "runner.agent.results"
    assert planning.build_plan.__module__ == "runner.workflow.planning"
    assert reviewing.review_task.__module__ == "runner.workflow.reviewing"
    assert ai.run_ai_validator.__module__ == "runner.workflow.validation.ai"
    assert file.run_file_validator.__module__ == "runner.workflow.validation.file"
    assert project_policy.protected_paths.__module__ == "runner.config.project_policy"
