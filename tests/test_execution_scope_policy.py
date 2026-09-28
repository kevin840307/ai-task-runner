from pathlib import Path

from runner.errors import RunnerError, is_transient_error


def test_transient_service_error_is_classified_for_stage_retry():
    error = RunnerError("service unavailable")
    error.transient = True
    assert is_transient_error(error)


def test_flow_engine_does_not_own_technical_retry_or_sessions():
    root = Path(__file__).resolve().parents[1]
    source = (root / "runner" / "workflow" / "flow_engine.py").read_text(encoding="utf-8")
    for token in (
        "is_transient_error",
        "_fresh_session",
        "sleep_with_heartbeat",
        "stage_retries",
        ".ask(",
    ):
        assert token not in source
