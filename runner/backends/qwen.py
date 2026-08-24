"""Qwen CLI backend."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..config.defaults import DEFAULT_QWEN_COMMAND
from ..runtime.process import run_process

from ..model.backend import ModelBackend, ModelMode, BackendResult, ensure_project_rules
from ..model.errors import BackendError
from .qwen_args import configure_qwen_args


class QwenBackend(ModelBackend):
    name = "qwen"
    default_command = DEFAULT_QWEN_COMMAND
    sandbox_flags = ("-s", "--sandbox")

    @classmethod
    def configure_args(
        cls,
        mode: ModelMode,
        extra_args: Sequence[str],
        *,
        allow_project_read: bool = False,
    ) -> list[str]:
        return configure_qwen_args(
            mode,
            extra_args,
            allow_project_read=allow_project_read,
        )

    def build_command(self, prompt: str, session_id: str) -> list[str]:
        if not prompt.strip():
            raise BackendError("qwen prompt is empty")
        if session_id and any(
            value in {"-s", "--sandbox"} for value in self.extra_args
        ):
            bridge_sandbox_session(self.root, session_id)
        session_args = ["--resume", session_id] if session_id else []
        return [
            *self.base_command,
            *session_args,
            "--output-format",
            "stream-json",
            *self.extra_args,
        ]

    def stdin_prompt(self, prompt: str) -> str:
        return prompt

    def decode(self, raw: str) -> BackendResult:
        values = self.parse_json_events(raw)
        if not values:
            return BackendResult(raw)

        session_id = self.find_session_id(values)
        result = self._find_result(values)
        return BackendResult(result if result is not None else raw, session_id)

    def error_output(self, raw: str) -> str:
        values = self.parse_json_events(raw)
        if not values:
            return raw
        return (
            self._find_error_message(values)
            or self._find_result(values)
            or self._find_assistant_text(values)
            or raw
        )

    def prepare_project(self) -> list[Path]:
        return [ensure_qwen_rules(self.root)]

    def update_goal_reference(self, goal_file: str | None) -> None:
        update_qwen_goal_reference(self.root, goal_file)

    def context_snapshot(self, session_id: str) -> str:
        """Run Qwen's read-only /context display command for diagnostics only."""
        return self._session_command(session_id, "/context", timeout=30)

    def context_usage_percent(self, snapshot: str) -> float | None:
        match = re.search(r"Used\s+[0-9.]+[kKmM]?\s+tokens\s+\(([0-9.]+)%\)", snapshot)
        return float(match.group(1)) if match else None

    def compress_session(self, session_id: str) -> str:
        """Use Qwen's non-AI fast compaction on an existing session."""
        return self._session_command(session_id, "/compress-fast", timeout=60)

    def _session_command(self, session_id: str, command: str, timeout: int) -> str:
        if not session_id:
            return ""
        if any(value in self.sandbox_flags for value in self.extra_args):
            bridge_sandbox_session(self.root, session_id)
        try:
            result = run_process(
                [*self.base_command, "-p", command, "--resume", session_id, *self.extra_args],
                self.root,
                min(self.timeout, timeout),
            )
        except Exception as error:
            return f"ERROR: {type(error).__name__}: {error}"
        output = result.output.strip()
        if result.timed_out:
            return f"ERROR: {command} timed out | {output}".strip()
        if result.return_code:
            return f"ERROR: {command} exit {result.return_code} | {output}".strip()
        return output

    @staticmethod
    def _find_result(values: Sequence[Any]) -> str | None:
        for value in reversed(values):
            items = value if isinstance(value, list) else [value]
            for item in reversed(items):
                if isinstance(item, dict) and isinstance(item.get("result"), str):
                    return item["result"]
        return None

    @staticmethod
    def _find_error_message(values: Sequence[Any]) -> str | None:
        for value in reversed(values):
            items = value if isinstance(value, list) else [value]
            for item in reversed(items):
                if not isinstance(item, dict):
                    continue
                error = item.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    return error["message"]
                if isinstance(item.get("error"), str):
                    return item["error"]
        return None

    @staticmethod
    def _find_assistant_text(values: Sequence[Any]) -> str | None:
        for value in reversed(values):
            items = value if isinstance(value, list) else [value]
            for item in reversed(items):
                if not isinstance(item, dict):
                    continue
                message = item.get("message")
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    ]
                    text = "\n".join(part for part in parts if part)
                    if text:
                        return text
        return None


def ensure_qwen_rules(root: Path) -> Path:
    """Create or extend the Qwen project rule file."""
    return ensure_project_rules(root, "QWEN.md")

def bridge_sandbox_session(
    root: Path,
    session_id: str,
    projects: Path | None = None,
) -> None:
    """Expose a container-recorded chat at Qwen's host project path."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", session_id):
        raise BackendError("invalid Qwen session id")
    projects = projects or Path.home() / ".qwen" / "projects"
    project_root = str(root.resolve())
    if os.name == "nt":
        project_root = project_root.lower()
    project_id = re.sub(r"[^a-zA-Z0-9]", "-", project_root)
    target = projects / project_id / "chats" / f"{session_id}.jsonl"
    try:
        sources = [
            path for path in projects.glob(f"*/chats/{session_id}.jsonl")
            if path != target
        ]
        if not sources:
            return
        source = max(sources, key=lambda path: path.stat().st_mtime_ns)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for line in source.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if isinstance(record, dict) and "cwd" in record:
                record["cwd"] = str(root.resolve())
            lines.append(json.dumps(
                record, ensure_ascii=False, separators=(",", ":")
            ))
        temporary = target.with_suffix(".jsonl.tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    except (OSError, json.JSONDecodeError) as error:
        raise BackendError("invalid Qwen sandbox session") from error



GOAL_REFERENCE_START = "<!-- AI-TASK-RUNNER:GOAL-REFERENCE -->"
GOAL_REFERENCE_END = "<!-- /AI-TASK-RUNNER:GOAL-REFERENCE -->"


def update_qwen_goal_reference(root: Path, goal_file: str | None) -> Path:
    """Maintain a replaceable goal-file reference in the project QWEN.md."""
    path = ensure_qwen_rules(root)
    text = path.read_text(encoding="utf-8")
    start = text.find(GOAL_REFERENCE_START)
    if start >= 0:
        end = text.find(GOAL_REFERENCE_END, start)
        if end >= 0:
            text = (text[:start] + text[end + len(GOAL_REFERENCE_END):]).rstrip()
    if goal_file:
        reference = Path(goal_file).expanduser().resolve().as_posix()
        text += f"""

{GOAL_REFERENCE_START}
Original requirement file: {reference}

If the original requirements are unclear, missing from context, or appear to
conflict with the current task or feedback, reread this file before continuing.
The original requirements remain authoritative; review or validator feedback
does not replace or narrow them.
{GOAL_REFERENCE_END}
"""
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path
