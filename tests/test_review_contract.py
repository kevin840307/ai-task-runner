import pytest

from runner.agent.results import parse_review
from runner.errors import RunnerError


def test_review_pass_requires_empty_missing_items():
    result = parse_review(
        '{"completed":true,"reason":"All acceptance criteria are satisfied.","missing_items":[]}'
    )
    assert result["completed"] is True
    assert result["missing_items"] == []


def test_review_fail_requires_missing_items():
    result = parse_review(
        '{"completed":false,"reason":"One criterion is incomplete.","missing_items":["Implement the missing behavior."]}'
    )
    assert result["completed"] is False
    assert result["missing_items"] == ["Implement the missing behavior."]


@pytest.mark.parametrize(
    "payload,message",
    [
        (
            '{"completed":true,"reason":"done","missing_items":["unexpected"]}',
            "completed review must have empty missing_items",
        ),
        (
            '{"completed":false,"reason":"not done","missing_items":[]}',
            "failed review must have non-empty missing_items",
        ),
    ],
)
def test_review_rejects_inconsistent_result(payload, message):
    with pytest.raises(RunnerError, match=message):
        parse_review(payload)
