"""Backward-compatible import for the renamed WorkflowRunner."""

from .workflow_runner import WorkflowRunner

TaskRunner = WorkflowRunner

__all__ = ["TaskRunner", "WorkflowRunner"]
