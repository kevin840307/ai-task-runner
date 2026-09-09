"""Atomic text-resource helpers for editor integrations."""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Callable

from .errors import RunnerError
from .utils.files import io_path

Validator = Callable[[str], None]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path: str | Path) -> tuple[str, str]:
    source = Path(path).expanduser().resolve()
    try:
        text = io_path(source).read_text(encoding="utf-8-sig")
    except OSError as error:
        raise RunnerError(f"cannot read resource: {source}: {error}") from error
    return text, text_hash(text)


def _check_expected_hash(path: Path, expected_hash: str | None) -> None:
    if expected_hash is not None and (
        not io_path(path).exists() or read_text(path)[1] != expected_hash
    ):
        raise RunnerError(f"resource changed since it was read: {path}")


def write_text(
    path: str | Path,
    text: str,
    *,
    expected_hash: str | None = None,
    validate: Validator | None = None,
) -> str:
    """Validate and atomically replace one UTF-8 text resource."""
    if not isinstance(text, str):
        raise ValueError("resource text must be a string")  # noqa: TRY004
    target = Path(path).expanduser().resolve()
    if validate is not None:
        validate(text)
    _check_expected_hash(target, expected_hash)
    io_path(target.parent).mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        io_path(temp).write_text(text, encoding="utf-8")
        os.replace(io_path(temp), io_path(target))
    except OSError as error:
        try:
            io_path(temp).unlink(missing_ok=True)
        except OSError:
            pass
        raise RunnerError(f"cannot write resource: {target}: {error}") from error
    return text_hash(text)


def delete(path: str | Path, *, expected_hash: str | None = None) -> None:
    target = Path(path).expanduser().resolve()
    _check_expected_hash(target, expected_hash)
    try:
        io_path(target).unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise RunnerError(f"cannot delete resource: {target}: {error}") from error


__all__ = ["delete", "read_text", "text_hash", "write_text"]
