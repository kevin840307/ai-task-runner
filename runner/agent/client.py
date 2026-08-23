"""Backward-compatible module alias; Agent implementation lives in agent.py."""
import sys as _sys
from . import agent as _impl
_sys.modules[__name__] = _impl
