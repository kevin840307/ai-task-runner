from runner.model.model import BackendError
from runner.errors import RunnerError, diagnostic_error


def test_diagnostic_error_finds_nested_backend_error():
    backend = BackendError(
        "qwen exit 1",
        return_code=1,
        elapsed=12.5,
        output="raw output",
        command_mode="resume",
        session_source_event="event[2]:system",
    )
    try:
        try:
            raise backend
        except BackendError as error:
            raise RunnerError("session unavailable") from error
    except RunnerError as error:
        wrapped = RunnerError("task failed")
        wrapped.__cause__ = error

    found = diagnostic_error(wrapped)

    assert found is backend
    assert found.return_code == 1
    assert found.elapsed == 12.5
    assert found.command_mode == "resume"
    assert found.session_source_event == "event[2]:system"


def test_diagnostic_error_handles_plain_error():
    assert diagnostic_error(RunnerError("plain")) is None
