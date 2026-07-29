"""Documentation must stay aligned with the public v1.1.1 contract."""
from __future__ import annotations

from pathlib import Path

from ai_task_runner import parser
from runner.api import RunRequest
from runner.version import __version__

ROOT = Path(__file__).resolve().parents[1]
DOCS = {
    "README": ROOT / "README.md",
    "DESIGN": ROOT / "docs" / "DESIGN.md",
    "USER_GUIDE": ROOT / "docs" / "USER_GUIDE.md",
    "TEST_MATRIX": ROOT / "docs" / "TEST_MATRIX.md",
    "PROJECT_GUIDE": ROOT / "docs" / "PROJECT_GUIDE.md",
}


def _text(name: str) -> str:
    return DOCS[name].read_text(encoding="utf-8")


def test_required_documents_exist_and_use_current_version():
    for path in DOCS.values():
        assert path.is_file()
        assert __version__ in path.read_text(encoding="utf-8")


def test_timeout_defaults_match_cli_api_and_manual():
    request = RunRequest(goal="x", validator="ai")
    args = parser().parse_args(["--goal", "x", "--validator", "ai"])
    guide = _text("USER_GUIDE")
    assert request.agent_timeout == args.agent_timeout == 7200
    assert request.planning_timeout == args.planning_timeout == 600
    assert (
        request.agent_idle_after_change_timeout
        == args.agent_idle_after_change_timeout
        == 900
    )
    assert request.validator_timeout == args.validator_timeout == 1200
    assert "`--agent-timeout` | `7200`" in guide
    assert "`--planning-timeout` | `600`" in guide
    assert "`--agent-idle-after-change-timeout` | `900`" in guide
    assert "`--validator-timeout` | `1200`" in guide


def test_canonical_api_resume_and_24h_boundaries_are_documented():
    combined = "\n".join(_text(name) for name in DOCS)
    assert "from runner import RunRequest, run" in combined
    assert "--goal-file" in combined
    assert "Resume does not require repeating `--goal`" in _text("USER_GUIDE")
    assert "the runner owns orchestration" in combined.lower()
    assert "Final Validator PASS" in combined
    assert "20,000" in combined
    assert "process_control.py" in _text("DESIGN")


def test_stale_timeout_and_version_claims_are_absent():
    combined = "\n".join(_text(name) for name in DOCS)
    stale = (
        "51 tests passed",
        "1.1.0",
        "--agent-idle-after-change-timeout 300",
        "`--validator-timeout` | `600`",
    )
    assert all(item not in combined for item in stale)


def test_agent_rule_files_and_task_prompt_shape_are_documented():
    combined = "\n".join(_text(name) for name in DOCS)
    assert "Qwen Code: `QWEN.md`" in combined
    assert "OpenCode: `AGENTS.md`" in combined
    assert "OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`" in combined
    assert "current task" in _text("PROJECT_GUIDE")
    assert "previous attempt output or diagnostic" in _text("PROJECT_GUIDE")
    assert "YAML batch mode is supported" in _text("PROJECT_GUIDE")


def test_external_validator_wrapper_is_documented():
    combined = "\n".join(_text(name) for name in DOCS)
    assert "external_command_validator.py" in combined
    assert "exe, bat, jar" in combined
    assert ".ai-task-runner/validator-reports/external-command/" in combined
    assert "log folders" in combined
