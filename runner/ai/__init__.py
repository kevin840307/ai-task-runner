"""Public AI subsystem."""
from .contracts import AIBackend, AIClientProtocol, BackendMode, BackendResult
from .errors import AIError, BackendError
from .client import AIClient, build_backend_args, configure_ai_client, create_ai_client
from .structured_output import AIValidationResult, ReviewResult

__all__ = [
    "AIBackend", "AIClient", "AIClientProtocol", "BackendMode", "BackendResult",
    "BackendError", "AIError", "build_backend_args", "create_ai_client", "configure_ai_client",
    "ReviewResult", "AIValidationResult",
]
