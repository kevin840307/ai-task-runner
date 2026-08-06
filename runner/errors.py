"""Shared user-facing error type."""


class RunnerError(RuntimeError):
    """A recoverable or user-facing runner error."""


class ReviewUnavailableError(RunnerError):
    """Review could not produce a decision within its configured budget."""
