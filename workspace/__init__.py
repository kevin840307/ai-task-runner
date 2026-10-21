"""Git workspace adapter for UI/Task orchestration.

Runner does not import this package. Callers prepare a filesystem project_root
here and pass that path through the existing Runner public contract.
"""

from .manager import WorkspaceManager, resolve_workspace_mode
from .model import PreparedWorkspace, WorkspaceBlockedError, WorkspaceError, WorkspaceResolution

__all__ = [
    "PreparedWorkspace",
    "WorkspaceBlockedError",
    "WorkspaceError",
    "WorkspaceManager",
    "WorkspaceResolution",
    "resolve_workspace_mode",
]
