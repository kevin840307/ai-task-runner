from argparse import Namespace
from pathlib import Path

import pytest

from runner.api import RunRequest
from runner.models import Task


def test_review_policy_defaults_and_cli_namespace():
    request = RunRequest(goal='g', project_root='.', validator='ai')
    request.validate()
    args = request.to_namespace()
    assert args.review_error_retries == 3
    assert args.strict_review is False


def test_review_retries_must_be_positive():
    request = RunRequest(goal='g', project_root='.', validator='ai', review_error_retries=0)
    with pytest.raises(ValueError, match='positive integer'):
        request.validate()


def test_task_review_audit_fields_round_trip():
    task = Task(id='c01-t001', title='t', description='d')
    assert task.review_skipped is False
    assert task.review_error_attempts == 0
    assert task.review_session_rebuilds == 0


def test_from_namespace_accepts_legacy_cli_namespace_without_review_fields():
    from argparse import Namespace

    from runner.defaults import DEFAULT_REVIEW_ERROR_RETRIES

    values = {
        "goal": "g",
        "goal_file": None,
        "project_root": ".",
        "script": None,
        "validator": "ai",
        "validator_prompt": "",
        "backend": "qwen",
        "command": None,
        "agent_arg": [],
        "validator_arg": [],
        "protect_file": [],
        "validator_timeout": 300,
        "agent_timeout": 0,
        "planning_timeout": 0,
        "agent_idle_after_change_timeout": 0,
        "max_attempts": 0,
        "max_cycles": 0,
        "retry_delay": 0,
        "retry_wait": 0,
        "retry_max_wait": 0,
        "work_dir": ".ai-task-runner",
        "resume": False,
        "force_new": False,
        "plan_only": False,
        "json_events": False,
    }

    request = RunRequest.from_namespace(Namespace(**values))

    assert request.review_error_retries == DEFAULT_REVIEW_ERROR_RETRIES
    assert request.strict_review is False
