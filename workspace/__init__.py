"""Git workspace adapter for UI/Task orchestration.

Runner does not import this package. Callers prepare a filesystem project_root
here and pass that path through the existing Runner public contract.
"""

from .manager import WorkspaceManager, resolve_workspace_mode
from .merge import MergeManager
from .merge_queue import MergeQueue, MergeQueueEntry
from .model import MergeResult, PreparedWorkspace, PublishResult, WorkspaceBlockedError, WorkspaceCleanupResult, WorkspaceError, WorkspaceResolution, WorkspaceSnapshot
from .publish import PublishManager

__all__ = [
    "MergeManager",
    "MergeQueue",
    "MergeQueueEntry",
    "MergeResult",
    "PreparedWorkspace",
    "PublishManager",
    "PublishResult",
    "WorkspaceBlockedError",
    "WorkspaceCleanupResult",
    "WorkspaceError",
    "WorkspaceManager",
    "WorkspaceResolution",
    "WorkspaceSnapshot",
    "resolve_workspace_mode",
]
