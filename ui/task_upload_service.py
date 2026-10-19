"""Transient Task file uploads materialized into Project-managed storage."""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
STAGED_TTL_SECONDS = 24 * 60 * 60
_ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_KINDS = {
    "validator": "validator",
    "ai-validator": "ai_validator_prompt_file",
    "goal": "goal_file",
}


class TaskUploadService:
    @staticmethod
    def _item_id(value: Any) -> str:
        item_id = str(value or "").strip()
        if not _ITEM_ID.fullmatch(item_id):
            raise ValueError("Invalid Task item identity")
        return item_id

    @staticmethod
    def _filename(value: Any) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        name = raw.rsplit("/", 1)[-1]
        if not name or name in {".", ".."} or "\x00" in name:
            raise ValueError("Invalid upload filename")
        if len(name) > 240:
            raise ValueError("Upload filename is too long")
        return name

    @staticmethod
    def _kind(value: Any) -> str:
        kind = str(value or "").strip().lower()
        if kind not in _KINDS:
            raise ValueError("Unsupported Task upload kind")
        return kind

    @staticmethod
    def _decode(value: Any) -> bytes:
        text = str(value or "")
        try:
            content = base64.b64decode(text.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise ValueError("Upload content is not valid base64") from exc
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("Uploaded file is too large")
        return content

    @staticmethod
    def _root(project: Path) -> Path:
        return project.resolve() / ".ai-task-runner" / "uploads"

    def _target(self, project: Path, item_id: str, kind: str, filename: str) -> Path:
        return (self._root(project) / self._item_id(item_id) / self._kind(kind) / self._filename(filename)).resolve()

    def _managed_target(self, project: Path, value: Any) -> Path | None:
        text = str(value or "").strip()
        if not text:
            return None
        raw = Path(text).expanduser()
        target = (raw if raw.is_absolute() else project.resolve() / raw).resolve()
        root = self._root(project).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None
        return target

    def _stage_path(self, project: Path, target: Path) -> Path:
        key = hashlib.sha256(os.path.normcase(str(target)).encode("utf-8")).hexdigest()
        return self._root(project) / ".staged" / (key + ".upload")

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass

    @staticmethod
    def _atomic_copy(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp-" + uuid.uuid4().hex)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass

    def _cleanup_stale(self, project: Path) -> None:
        folder = self._root(project) / ".staged"
        if not folder.is_dir():
            return
        cutoff = time.time() - STAGED_TTL_SECONDS
        for path in folder.glob("*.upload"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue

    def stage(
        self,
        project: Path,
        *,
        item_id: Any,
        kind: Any,
        filename: Any,
        content_base64: Any,
    ) -> dict[str, Any]:
        self._cleanup_stale(project)
        item_key = self._item_id(item_id)
        upload_kind = self._kind(kind)
        name = self._filename(filename)
        content = self._decode(content_base64)
        target = self._target(project, item_key, upload_kind, name)
        stage = self._stage_path(project, target)
        try:
            self._atomic_write(stage, content)
        except OSError as exc:
            raise ValueError(f"Could not stage uploaded file: {exc}") from exc
        return {
            "path": str(target),
            "item_id": item_key,
            "kind": upload_kind,
            "filename": name,
            "size": len(content),
            "staged": True,
        }

    def cancel(self, project: Path, path: Any) -> dict[str, Any]:
        target = self._managed_target(project, path)
        if target is None:
            return {"cancelled": False}
        stage = self._stage_path(project, target)
        existed = stage.exists()
        try:
            stage.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ValueError(f"Could not cancel staged upload: {exc}") from exc
        return {"cancelled": True, "staged": existed, "path": str(target)}

    def materialize_items(self, project: Path, items: list[dict[str, Any]]) -> list[str]:
        materialized: list[str] = []
        root = self._root(project).resolve()
        for item in items:
            item_id = self._item_id(item.get("item_id"))
            for kind, field in _KINDS.items():
                target = self._managed_target(project, item.get(field))
                if target is None:
                    continue
                expected_dir = (root / item_id / kind).resolve()
                if target.parent.resolve() != expected_dir:
                    raise ValueError(f"Managed upload path does not match Task item {item_id}")
                stage = self._stage_path(project, target)
                if stage.is_file():
                    try:
                        self._atomic_copy(stage, target)
                    except OSError as exc:
                        raise ValueError(f"Could not materialize uploaded file: {exc}") from exc
                    materialized.append(str(target))
                elif not target.is_file():
                    raise ValueError("Uploaded file is no longer staged; upload it again")
        return materialized

    def finalize(self, project: Path, paths: list[str]) -> None:
        for value in paths:
            target = self._managed_target(project, value)
            if target is None:
                continue
            try:
                self._stage_path(project, target).unlink()
            except OSError:
                pass

    def staged_exists(self, project: Path, path: Any) -> bool:
        target = self._managed_target(project, path)
        return bool(target is not None and self._stage_path(project, target).is_file())
