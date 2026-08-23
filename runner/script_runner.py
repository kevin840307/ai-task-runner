"""Compatibility alias for :mod:`runner.app.script_runner`."""
import sys as _sys
from .app import script_runner as _impl
_sys.modules[__name__] = _impl
