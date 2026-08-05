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
