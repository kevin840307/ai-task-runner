"""Documentation must stay aligned with the public v1.2.0 contract."""
from __future__ import annotations

from pathlib import Path

from ai_task_runner import parser
from runner.api import RunRequest
from runner.version import __version__

ROOT = Path(__file__).resolve().parents[1]
DOCS = {
    "README": ROOT / "README.md",
    "DESIGN": ROOT / "docs" / "design" / "DESIGN.md",
    "USER_GUIDE": ROOT / "docs" / "user" / "USER_GUIDE.md",
    "TEST_MATRIX": ROOT / "docs" / "development" / "TEST_MATRIX.md",
    "PROJECT_GUIDE": ROOT / "docs" / "development" / "PROJECT_GUIDE.md",
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
    assert "process_runner.py" in _text("DESIGN")


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
    guide = _text("PROJECT_GUIDE").lower()
    assert "current task" in guide
    assert "previous attempt output or diagnostic" in guide
    assert "YAML batch mode is supported" in _text("PROJECT_GUIDE")


def test_external_validator_wrapper_is_documented():
    combined = "\n".join(_text(name) for name in DOCS)
    assert "external_command_validator.py" in combined
    assert "exe, bat, jar" in combined
    assert ".ai-task-runner/validator-reports/external-command/" in combined
    assert "log folders" in combined


def test_bilingual_document_set_is_complete_and_linked():
    pairs = (
        ("README.md", "README.zh-TW.md"),
        ("docs/INDEX.md", "docs/INDEX.zh-TW.md"),
        ("docs/design/DESIGN.md", "docs/design/DESIGN.zh-TW.md"),
        ("docs/design/ARCHITECTURE.md", "docs/design/ARCHITECTURE.zh-TW.md"),
        ("docs/user/USER_GUIDE.md", "docs/user/USER_GUIDE.zh-TW.md"),
        ("docs/user/CLI_REFERENCE.md", "docs/user/CLI_REFERENCE.zh-TW.md"),
        ("docs/user/API_REFERENCE.md", "docs/user/API_REFERENCE.zh-TW.md"),
        ("docs/design/PROMPT_SESSION.md", "docs/design/PROMPT_SESSION.zh-TW.md"),
        ("docs/design/STATE_EVENTS.md", "docs/design/STATE_EVENTS.zh-TW.md"),
        ("docs/operations/SECURITY_PROTECTION.md", "docs/operations/SECURITY_PROTECTION.zh-TW.md"),
        ("docs/operations/OPERATIONS.md", "docs/operations/OPERATIONS.zh-TW.md"),
        ("docs/development/PROJECT_GUIDE.md", "docs/development/PROJECT_GUIDE.zh-TW.md"),
        ("docs/development/TEST_MATRIX.md", "docs/development/TEST_MATRIX.zh-TW.md"),
        ("docs/validator_templates/README.md", "docs/validator_templates/README.zh-TW.md"),
        ("examples/README.md", "examples/README.zh-TW.md"),
        ("smoke/README.md", "smoke/README.zh-TW.md"),
    )
    for english, chinese in pairs:
        assert (ROOT / english).is_file(), english
        assert (ROOT / chinese).is_file(), chinese


def test_validator_arg_and_maintenance_contract_are_documented():
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "README.md",
            ROOT / "README.zh-TW.md",
            ROOT / "docs" / "user" / "CLI_REFERENCE.md",
            ROOT / "docs" / "user" / "CLI_REFERENCE.zh-TW.md",
            ROOT / "docs" / "development" / "PROJECT_GUIDE.md",
            ROOT / "docs" / "development" / "PROJECT_GUIDE.zh-TW.md",
            ROOT / "AGENTS.md",
            ROOT / "QWEN.md",
        )
    )
    assert "--validator-arg" in combined
    assert "No project-specific hardcode" in combined or "禁止 project-specific hardcode" in combined
    assert "one shared implementation" in combined.lower()
    assert "minimum code" in combined.lower() or "最小程式碼" in combined


def test_all_human_facing_markdown_has_bilingual_pair():
    """Maintained documentation is bilingual; executable prompt/fixture files are excluded."""
    documents = [ROOT / "README.md"]
    documents.extend(
        path for path in (ROOT / "docs").rglob("*.md")
        if not path.name.endswith(".zh-TW.md")
    )
    documents.extend(
        path for path in (ROOT / "examples").rglob("README.md")
        if "project" not in path.parts
    )
    documents.append(ROOT / "smoke" / "README.md")

    for english in documents:
        chinese = english.with_name(f"{english.stem}.zh-TW{english.suffix}")
        assert chinese.is_file(), f"missing Traditional Chinese document for {english.relative_to(ROOT)}"


def test_bilingual_core_docs_cover_current_architecture_and_recovery():
    pairs = (
        (ROOT / "docs" / "design" / "DESIGN.md", ROOT / "docs" / "design" / "DESIGN.zh-TW.md"),
        (ROOT / "docs" / "development" / "PROJECT_GUIDE.md", ROOT / "docs" / "development" / "PROJECT_GUIDE.zh-TW.md"),
        (ROOT / "docs" / "user" / "USER_GUIDE.md", ROOT / "docs" / "user" / "USER_GUIDE.zh-TW.md"),
    )
    required = (
        "Same Session",
        "Fresh Session",
        "YAML",
        "stdin",
        "Final AI",
        "Plugin",
        "Prompt",
    )
    for english, chinese in pairs:
        en = english.read_text(encoding="utf-8")
        zh = chinese.read_text(encoding="utf-8")
        for token in required:
            assert token.lower() in en.lower(), (english, token)
            assert token.lower() in zh.lower(), (chinese, token)

    assert "next_flow" in (ROOT / "README.zh-TW.md").read_text(encoding="utf-8")
    assert "重新理解目前專案" not in (ROOT / "README.zh-TW.md").read_text(encoding="utf-8")
