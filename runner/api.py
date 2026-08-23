"""Compatibility alias for :mod:`runner.app.api`."""
import sys as _sys
from .app import api as _impl
_sys.modules[__name__] = _impl
