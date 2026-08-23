"""Shared strict value checks for public input and persisted state."""
from __future__ import annotations

from typing import TypeGuard


def is_integer(value: object) -> TypeGuard[int]:
    """Return whether value is an integer, excluding bool's int subclass."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value: object) -> TypeGuard[int | float]:
    """Return whether value is numeric, excluding bool's numeric subclass."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


__all__ = ["is_integer", "is_number"]
