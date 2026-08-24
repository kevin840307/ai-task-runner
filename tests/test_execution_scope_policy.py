from pathlib import Path

from runner.errors import RunnerError, is_transient_error


def test_transient_service_error_is_not_a_real_stage_failure():
    error = RunnerError("service unavailable")
    error.transient = True
    assert is_transient_error(error)


def test_pipeline_does_not_own_task_or_stage_specific_policy():
    root = Path(__file__).resolve().parents[1]
    source = (root / "runner/workflow/pipeline.py").read_text(encoding="utf-8")
    for token in ("task.attempts", "review_skipped", "validator_failure", "model.session_id", "failure_key"):
        assert token not in source
