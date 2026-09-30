"""Canonical documentation must match the minimal runtime contract."""
from __future__ import annotations

from pathlib import Path

from ai_task_runner import parser
from runner.api import RunRequest
from runner.version import __version__

ROOT = Path(__file__).resolve().parents[1]
DOCS = {
    "README": ROOT / "README.md",
    "README_ZH": ROOT / "README.zh-TW.md",
    "ARCHITECTURE": ROOT / "architecture.md",
    "FUTURE": ROOT / "future.txt",
    "DEV": ROOT / "DevFollow.txt",
}


def text(name: str) -> str:
    return DOCS[name].read_text(encoding="utf-8")


def test_canonical_documents_exist_and_readme_uses_current_version():
    for path in DOCS.values():
        assert path.is_file(), path
    assert f"Version: {__version__}" in text("README")
    assert f"版本：{__version__}" in text("README_ZH")


def test_retry_defaults_match_cli_api_and_documentation():
    request = RunRequest(goal="x", validator="ai")
    args = parser().parse_args(["--goal", "x", "--validator", "ai"])

    assert request.stage_retries == args.stage_retries == -1
    assert request.retry_delay == args.retry_delay == 5
    assert request.retry_max_delay == args.retry_max_delay == 300

    combined = text("README") + text("README_ZH")
    assert "stage_retries = -1" in combined
    assert "retry_delay = 5" in combined
    assert "retry_max_delay = 300" in combined


def test_timeout_defaults_match_cli_and_api():
    request = RunRequest(goal="x", validator="ai")
    args = parser().parse_args(["--goal", "x", "--validator", "ai"])
    assert request.agent_timeout == args.agent_timeout == 7200
    assert request.planning_timeout == args.planning_timeout == 600
    assert request.validator_timeout == args.validator_timeout == 1200
    assert (
        request.agent_idle_after_change_timeout
        == args.agent_idle_after_change_timeout
        == 900
    )


def test_docs_describe_one_runtime_and_structured_assets():
    combined = "\n".join(text(name) for name in DOCS)
    for token in (
        "WorkflowRunner",
        "FlowEngine",
        "StageExecutor",
        "StateStore",
        "runner/assets/workflows/",
        "prompts/",
        "Dynamic Handoff",
        "Discussion / Group Chat",
    ):
        assert token in combined

    assert "<project>/.ai-task-runner/assets/" in combined


def test_readmes_document_cli_yaml_and_24h_contract():
    for name in ("README", "README_ZH"):
        value = text(name)
        assert "--stage-retries" in value
        assert "--retry-delay" in value
        assert "--retry-max-delay" in value
        assert "YAML List" in value
        assert "qwen_live_reliability_24h.bat" in value
        assert "Same Session" in value
        assert "Fresh Session" in value


def test_deleted_runtime_modules_and_asset_paths_stay_absent():
    removed_paths = (
        "runner/workflow/system",
        "runner/workflow/custom",
        "runner/prompts/system",
        "runner/prompts/stages",
        "runner/workflows",
        "runner/task_runner.py",
        "runner/workflow/pipeline.py",
        "runner/workflow/linear_routing.py",
        "runner/workflow/semantic_routing.py",
        "runner/ai",
        "runner/backends",
        "runner/project",
        "runner/utils/files.py",
    )
    for relative in removed_paths:
        assert not (ROOT / relative).exists(), relative


def test_architecture_keeps_behavior_ownership_explicit():
    value = text("ARCHITECTURE")
    assert "Stage" in value
    assert "StageExecutor" in value
    assert "technical reliability" in value
    assert "FlowEngine" in value
    assert "semantic PASS/FAIL navigation" in value
    assert "StateStore" in value
    assert "Dynamic Handoff is the only multi-agent runtime primitive" in value


def test_future_todo_keeps_linear_first_and_future_families_deferred():
    value = text("FUTURE")
    assert "Linear Workflow with Rollback / Loop" in value
    assert "Dynamic Handoff" in value
    assert "Discussion / Group Chat" in value
    assert "Future - do not implement yet" in value
    assert "high-density soak" in value
