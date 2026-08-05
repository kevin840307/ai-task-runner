from argparse import Namespace
from pathlib import Path

import pytest

from ai_task_runner import parser
from runner.api import RunRequest
from runner.defaults import (
    DEFAULT_FINAL_AI_REQUIRED_PASSES,
    DEFAULT_FINAL_AI_VALIDATIONS,
)
from runner.validation import format_ai_validator_runs


def test_final_ai_defaults_and_cli_options():
    args = parser().parse_args(["--goal", "g", "--validator", "ai"])
    assert args.final_ai_validations == DEFAULT_FINAL_AI_VALIDATIONS == 1
    assert args.final_ai_required_passes == DEFAULT_FINAL_AI_REQUIRED_PASSES == 1

    args = parser().parse_args([
        "--goal", "g", "--validator", "ai",
        "--final-ai-validations", "3",
        "--final-ai-required-passes", "2",
    ])
    request = RunRequest.from_namespace(args)
    request.validate()
    assert request.final_ai_validations == 3
    assert request.final_ai_required_passes == 2


def test_final_ai_required_passes_range():
    with pytest.raises(ValueError, match="between 1"):
        RunRequest(
            goal="g", validator="ai",
            final_ai_validations=2,
            final_ai_required_passes=3,
        ).validate()


def test_legacy_namespace_gets_final_ai_defaults():
    args = parser().parse_args(["--goal", "g", "--validator", "ai"])
    del args.final_ai_validations
    del args.final_ai_required_passes
    request = RunRequest.from_namespace(args)
    assert request.final_ai_validations == 1
    assert request.final_ai_required_passes == 1


def test_two_passes_and_one_error_is_pass():
    output = format_ai_validator_runs([
        {"passed": True, "reason": "ok", "missing_items": []},
        {"error": "timeout"},
        {"passed": True, "reason": "ok", "missing_items": []},
    ], required=2, total=3)
    assert '"passed": true' in output


def test_any_explicit_fail_is_not_outvoted():
    output = format_ai_validator_runs([
        {"passed": True, "reason": "ok", "missing_items": []},
        {"passed": False, "reason": "bug", "missing_items": ["unsafe overwrite"]},
        {"passed": True, "reason": "ok", "missing_items": []},
    ], required=2, total=3)
    assert output.startswith("AI_VALIDATION_FAILED")
    assert "unsafe overwrite" in output


def test_each_final_ai_validation_uses_new_session(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from runner import validation
    from runner.models import RunState

    sessions = []
    replies = iter([
        '{"passed":true,"reason":"ok","missing_items":[],"checks_run":[],"suggested_checks":[]}',
        '{"passed":true,"reason":"ok","missing_items":[],"checks_run":[],"suggested_checks":[]}',
        '{"passed":true,"reason":"ok","missing_items":[],"checks_run":[],"suggested_checks":[]}',
    ])

    class FakeAgent:
        def __init__(self, **kwargs):
            sessions.append(kwargs["session_id"])

    monkeypatch.setattr(validation, "AgentClient", FakeAgent)
    monkeypatch.setattr(
        validation,
        "readonly_ask",
        lambda *args, **kwargs: (next(replies), [], []),
    )
    monkeypatch.setattr(
        validation,
        "retry_model_call",
        lambda call, *args, **kwargs: call(),
    )

    args = SimpleNamespace(
        backend="qwen",
        command=None,
        agent_timeout=0,
        agent_idle_after_change_timeout=0,
        validator_prompt="",
        retry_wait=0,
        retry_max_wait=0,
        final_ai_validations=3,
        final_ai_required_passes=2,
    )
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    passed, output = validation.run_ai_validator(
        args, tmp_path, tmp_path / ".work", state, [], object(), [], 1
    )

    assert passed is True
    assert sessions == ["", "", ""]
    assert '"passes": 3' in output
