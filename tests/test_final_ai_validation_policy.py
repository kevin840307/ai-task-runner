import pytest

from ai_task_runner import parser
from runner.api import RunRequest
from runner.config.defaults import (
    DEFAULT_FINAL_AI_REQUIRED_PASSES,
    DEFAULT_FINAL_AI_VALIDATIONS,
)
from runner.workflow.validation.ai import format_ai_validator_runs


def test_final_ai_defaults_and_cli_options():
    args = parser().parse_args(["--goal", "g", "--validator", "ai"])
    assert args.final_ai_validations == DEFAULT_FINAL_AI_VALIDATIONS == 1
    assert args.final_ai_required_passes == DEFAULT_FINAL_AI_REQUIRED_PASSES == 0

    args = parser().parse_args([
        "--goal", "g", "--validator", "ai", "--ai-validator-count", "3",
    ])
    assert args.final_ai_validations == 3

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
    with pytest.raises(ValueError, match="must be 0 or"):
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
    assert request.final_ai_required_passes == 0


def test_two_passes_and_one_error_is_pass():
    output = format_ai_validator_runs([
        {"passed": True, "reason": "ok", "missing_items": []},
        {"error": "timeout"},
        {"passed": True, "reason": "ok", "missing_items": []},
    ], required=2, total=3)
    assert '"passed": true' in output


def test_majority_outvotes_one_explicit_fail():
    output = format_ai_validator_runs([
        {"passed": True, "reason": "ok", "missing_items": []},
        {"passed": False, "reason": "bug", "missing_items": ["unsafe overwrite"]},
        {"passed": True, "reason": "ok", "missing_items": []},
    ], required=2, total=3)
    assert '"passed": true' in output


def test_ai_validation_stops_after_quorum_in_independent_sessions(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from runner.workflow.validation import ai as ai_validation
    from runner.engine.models import RunState

    sessions = []
    replies = iter([
        '{"passed":true,"reason":"ok","missing_items":[],"checks_run":[],"suggested_checks":[]}',
        '{"passed":true,"reason":"ok","missing_items":[],"checks_run":[],"suggested_checks":[]}',
        '{"passed":true,"reason":"ok","missing_items":[],"checks_run":[],"suggested_checks":[]}',
    ])

    class FakeAgent:
        def __init__(self, **kwargs):
            sessions.append(kwargs["session_id"])

    monkeypatch.setattr(ai_validation, "AgentClient", FakeAgent)
    monkeypatch.setattr(
        ai_validation,
        "readonly_ask",
        lambda *args, **kwargs: (next(replies), [], []),
    )
    monkeypatch.setattr(
        ai_validation,
        "retry_model_call",
        lambda call, *args, **kwargs: call(),
    )

    args = SimpleNamespace(
        backend="qwen",
        command=None,
        agent_timeout=0,
        agent_idle_after_change_timeout=0,
        retry_wait=0,
        retry_max_wait=0,
        final_ai_validations=3,
        final_ai_required_passes=2,
    )
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    passed, output = ai_validation.run_ai_validator(
        args, tmp_path, tmp_path / ".work", state, [], object(), 1
    )

    assert passed is True
    assert sessions == ["", ""]
    assert '"passes": 2' in output
    assert '"completed_validations": 2' in output


def test_run_ai_validator_uses_majority_and_runs_all_sessions(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from runner.workflow.validation import ai as ai_validation
    from runner.engine.models import RunState

    sessions = []
    replies = iter([
        '{"passed":true,"reason":"ok","missing_items":[],"checks_run":[],"suggested_checks":[]}',
        '{"passed":false,"reason":"issue","missing_items":["x"],"checks_run":[],"suggested_checks":[]}',
        '{"passed":true,"reason":"ok","missing_items":[],"checks_run":[],"suggested_checks":[]}',
    ])

    class FakeAgent:
        def __init__(self, **kwargs):
            sessions.append(kwargs["session_id"])

    monkeypatch.setattr(ai_validation, "AgentClient", FakeAgent)
    monkeypatch.setattr(
        ai_validation,
        "readonly_ask",
        lambda *a, **k: (next(replies), [], []),
    )
    monkeypatch.setattr(
        ai_validation,
        "retry_model_call",
        lambda call, *a, **k: call(),
    )

    args = SimpleNamespace(
        backend="qwen", command=None, agent_timeout=0,
        agent_idle_after_change_timeout=0, retry_wait=0, retry_max_wait=0,
        final_ai_validations=3, final_ai_required_passes=0,
    )
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    passed, output = ai_validation.run_ai_validator(
        args, tmp_path, tmp_path / ".work", state, [], object(), 1, "custom"
    )

    assert passed is True
    assert sessions == ["", "", ""]
    assert '"required_passes": 2' in output


def test_ai_validation_stops_when_quorum_is_impossible(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from runner.engine.models import RunState
    from runner.workflow.validation import ai as ai_validation

    sessions = []

    class FakeAgent:
        def __init__(self, **kwargs):
            sessions.append(kwargs["session_id"])

    monkeypatch.setattr(ai_validation, "AgentClient", FakeAgent)
    monkeypatch.setattr(
        ai_validation,
        "readonly_ask",
        lambda *args, **kwargs: (
            '{"passed":false,"reason":"issue","missing_items":["x"],'
            '"checks_run":[],"suggested_checks":[]}',
            [],
            [],
        ),
    )
    monkeypatch.setattr(
        ai_validation,
        "retry_model_call",
        lambda call, *args, **kwargs: call(),
    )
    args = SimpleNamespace(
        backend="qwen",
        command=None,
        agent_timeout=0,
        agent_idle_after_change_timeout=0,
        retry_wait=0,
        retry_max_wait=0,
        final_ai_validations=3,
        final_ai_required_passes=2,
    )
    state = RunState(run_id="r", goal="g", project_root=str(tmp_path))

    passed, output = ai_validation.run_ai_validator(
        args, tmp_path, tmp_path / ".work", state, [], object(), 1
    )

    assert passed is False
    assert sessions == ["", ""]
    assert '"completed_validations": 2' in output


def test_mixed_validation_runs_hard_gate_then_ai_vote(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from runner.engine import core
    from runner.engine.models import RunState

    calls = []
    monkeypatch.setattr(
        core,
        "run_file_validator",
        lambda *args, **kwargs: (calls.append("file") or True, "hard ok"),
    )
    monkeypatch.setattr(
        core,
        "run_ai_validator",
        lambda *args, **kwargs: (calls.append(("ai", args[-1])) or True, "ai ok"),
    )

    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(
        backend="qwen", agent_arg=[], validator_timeout=10, validator_arg=[],
        ai_validator_prompt="check architecture", validator_prompt="",
    )
    runner.root = tmp_path
    runner.work = tmp_path / ".work"
    runner.state_file = runner.work / "state.json"
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    runner.protected = []
    runner.ui = object()
    runner.validator = tmp_path / "validator.py"
    runner.ai_validation = False

    passed, output = runner._run_validator()

    assert passed is True
    assert calls == ["file", ("ai", "check architecture")]
    assert output == "FILE_VALIDATION_PASS\nai ok"


def test_mixed_validation_skips_ai_when_hard_gate_fails(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from runner.engine import core
    from runner.engine.models import RunState

    calls = []
    monkeypatch.setattr(
        core,
        "run_file_validator",
        lambda *args, **kwargs: (calls.append("file") or False, "hard fail"),
    )
    monkeypatch.setattr(
        core,
        "run_ai_validator",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("AI must not run")),
    )

    runner = core.TaskRunner.__new__(core.TaskRunner)
    runner.args = SimpleNamespace(
        backend="qwen", agent_arg=[], validator_timeout=10, validator_arg=[],
        ai_validator_prompt="check architecture", validator_prompt="",
    )
    runner.root = tmp_path
    runner.work = tmp_path / ".work"
    runner.state_file = runner.work / "state.json"
    runner.state = RunState(run_id="r", goal="g", project_root=str(tmp_path))
    runner.protected = []
    runner.ui = object()
    runner.validator = tmp_path / "validator.py"
    runner.ai_validation = False

    assert runner._run_validator() == (False, "hard fail")
    assert calls == ["file"]


def test_yaml_item_supports_mixed_ai_validation_settings(tmp_path):
    from runner.script_runner import load_yaml_script

    script = tmp_path / "tasks.yaml"
    script.write_text(
        """
- prompt: build it
  validator: validation.py
  ai_validator_prompt: >-
    Check architecture and genericity.
  ai_validator_count: 3
  ai_validator_required_passes: 2
""",
        encoding="utf-8",
    )

    [item] = load_yaml_script(script)
    assert item["validator"] == "validation.py"
    assert item["ai_validator_prompt"] == "Check architecture and genericity."
    assert item["ai_validator_count"] == 3
    assert item["ai_validator_required_passes"] == 2


def test_yaml_legacy_validator_shape_still_works(tmp_path):
    from runner.script_runner import load_yaml_script

    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: old task\n  validator: validation.py\n",
        encoding="utf-8",
    )
    [item] = load_yaml_script(script)
    assert item["validator"] == "validation.py"
    assert item["ai_validator_prompt"] == ""
    assert "ai_validator_count" not in item
