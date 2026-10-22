"""Durable FIFO merge queue for one repository + captured target branch."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import WorkspaceError
from .worktree import merge_queue_lock, repository_identity

_STATE_VERSION = 1


@dataclass(frozen=True)
class MergeQueueEntry:
    seq: int
    task_id: str
    run_number: int
    source_sha: str
    source_base_sha: str


class MergeQueue:
    """Persist merge order independently from Runner/process lifetime."""

    def __init__(self, repo: Path, target_branch: str) -> None:
        self.repo = Path(repo).expanduser().resolve()
        self.target_branch = str(target_branch or "").strip()
        if not self.target_branch:
            raise WorkspaceError("Merge queue target branch is required")
        key = hashlib.sha256(self.target_branch.encode("utf-8")).hexdigest()[:24]
        self.path = repository_identity(self.repo) / "ai-task-runner" / "merge-queues" / f"{key}.json"

    def enqueue(
        self,
        *,
        task_id: str,
        run_number: int,
        source_sha: str,
        source_base_sha: str,
    ) -> tuple[MergeQueueEntry, bool]:
        identity = (str(task_id), int(run_number))
        with merge_queue_lock(self.repo, self.target_branch):
            state = self._load()
            entries = state["entries"]
            for index, raw in enumerate(entries):
                if (raw["task_id"], raw["run_number"]) != identity:
                    continue
                if raw["source_sha"] != source_sha or raw["source_base_sha"] != source_base_sha:
                    raw["source_sha"] = str(source_sha)
                    raw["source_base_sha"] = str(source_base_sha)
                    self._write(state)
                return self._entry(raw), index == 0

            seq = state["next_seq"]
            raw = {
                "seq": seq,
                "task_id": identity[0],
                "run_number": identity[1],
                "source_sha": str(source_sha),
                "source_base_sha": str(source_base_sha),
            }
            entries.append(raw)
            state["next_seq"] = seq + 1
            self._write(state)
            return self._entry(raw), len(entries) == 1

    def complete(self, entry: MergeQueueEntry) -> None:
        """Remove only the current queue head; retries are idempotent."""
        self._release(entry.task_id, entry.run_number, expected_seq=entry.seq)

    def release_head(self, *, task_id: str, run_number: int) -> bool:
        """Release one abandoned/fallback head without creating a new queue entry."""
        return self._release(str(task_id), int(run_number), expected_seq=None)

    def _release(self, task_id: str, run_number: int, *, expected_seq: int | None) -> bool:
        with merge_queue_lock(self.repo, self.target_branch):
            state = self._load()
            entries = state["entries"]
            index = next(
                (
                    i
                    for i, raw in enumerate(entries)
                    if raw["task_id"] == task_id and raw["run_number"] == run_number
                ),
                -1,
            )
            if index < 0:
                return False
            raw = entries[index]
            if index != 0 or (expected_seq is not None and raw["seq"] != expected_seq):
                raise WorkspaceError("Cannot complete a non-head merge queue entry")
            entries.pop(0)
            self._write(state)
            return True

    @staticmethod
    def _entry(raw: dict[str, Any]) -> MergeQueueEntry:
        return MergeQueueEntry(
            seq=int(raw["seq"]),
            task_id=str(raw["task_id"]),
            run_number=int(raw["run_number"]),
            source_sha=str(raw["source_sha"]),
            source_base_sha=str(raw["source_base_sha"]),
        )

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "version": _STATE_VERSION,
                "target_branch": self.target_branch,
                "next_seq": 1,
                "entries": [],
            }
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceError(f"Merge queue state is invalid: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("version") != _STATE_VERSION:
            raise WorkspaceError("Unsupported merge queue state version")
        if raw.get("target_branch") != self.target_branch:
            raise WorkspaceError("Merge queue target branch does not match its state")
        next_seq = raw.get("next_seq")
        entries = raw.get("entries")
        if not isinstance(next_seq, int) or next_seq <= 0 or not isinstance(entries, list):
            raise WorkspaceError("Merge queue state is invalid")

        seen_identity: set[tuple[str, int]] = set()
        seen_seq: set[int] = set()
        normalized: list[dict[str, Any]] = []
        previous_seq = 0
        for value in entries:
            if not isinstance(value, dict):
                raise WorkspaceError("Merge queue contains an invalid entry")
            try:
                seq = int(value["seq"])
                run_number = int(value["run_number"])
            except (KeyError, TypeError, ValueError) as exc:
                raise WorkspaceError("Merge queue contains an invalid entry") from exc
            task_id = str(value.get("task_id") or "")
            source_sha = str(value.get("source_sha") or "")
            source_base_sha = str(value.get("source_base_sha") or "")
            identity = (task_id, run_number)
            if (
                seq <= previous_seq
                or seq in seen_seq
                or run_number <= 0
                or not task_id
                or not source_sha
                or not source_base_sha
                or identity in seen_identity
            ):
                raise WorkspaceError("Merge queue contains an invalid entry")
            seen_seq.add(seq)
            seen_identity.add(identity)
            previous_seq = seq
            normalized.append(
                {
                    "seq": seq,
                    "task_id": task_id,
                    "run_number": run_number,
                    "source_sha": source_sha,
                    "source_base_sha": source_base_sha,
                }
            )
        if normalized and next_seq <= normalized[-1]["seq"]:
            raise WorkspaceError("Merge queue next sequence is invalid")
        return {
            "version": _STATE_VERSION,
            "target_branch": self.target_branch,
            "next_seq": next_seq,
            "entries": normalized,
        }

    def _write(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)
