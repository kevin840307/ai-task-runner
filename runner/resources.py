"""Small atomic text-resource helpers shared by CLI/UI tooling."""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Callable

from .errors import RunnerError

Validator = Callable[[str], None]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path: str | Path) -> tuple[str, str]:
    source = Path(path).expanduser().resolve()
    try:
        text = source.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise RunnerError(f"cannot read resource: {source}: {error}") from error
    return text, text_hash(text)


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
    if expected_hash is not None:
        if not target.exists():
            raise RunnerError(f"resource changed since it was read: {target}")
        _, current_hash = read_text(target)
        if current_hash != expected_hash:
            raise RunnerError(f"resource changed since it was read: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, target)
    except OSError as error:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise RunnerError(f"cannot write resource: {target}: {error}") from error
    return text_hash(text)


def delete(path: str | Path, *, expected_hash: str | None = None) -> None:
    target = Path(path).expanduser().resolve()
    if expected_hash is not None:
        if not target.exists():
            raise RunnerError(f"resource changed since it was read: {target}")
        _, current_hash = read_text(target)
        if current_hash != expected_hash:
            raise RunnerError(f"resource changed since it was read: {target}")
    try:
        target.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise RunnerError(f"cannot delete resource: {target}: {error}") from error


__all__ = ["delete", "read_text", "text_hash", "write_text"]
