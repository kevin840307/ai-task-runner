"""Internal package for AI Task Runner orchestration."""

from .version import __version__

__all__ = ["RunRequest", "RunResult", "__version__", "run"]


def __getattr__(name: str):
    if name in {"RunRequest", "RunResult", "run"}:
        from .api import RunRequest, RunResult, run

        return {
            "RunRequest": RunRequest,
            "RunResult": RunResult,
            "run": run,
        }[name]
    raise AttributeError(name)
