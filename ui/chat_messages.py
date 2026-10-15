"""UI-owned conversation transcripts, independent of Runner execution logs."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from project_registry import project_file_lock

try:
    from .chat_index import ChatIndex
except ImportError:  # direct ui/main.py execution
    from chat_index import ChatIndex


class ChatMessages:
    def __init__(self, folder: Path, index: ChatIndex):
        self.folder = Path(folder)
        self.index = index

    def _chat(self, chat_id: str) -> dict:
        if not isinstance(chat_id, str) or len(chat_id) != 32 or any(c not in "0123456789abcdef" for c in chat_id):
            raise ValueError("Invalid Chat identity")
        match = next((row for row in self.index.list() if row.get("chat_id") == chat_id), None)
        if match is None:
            raise ValueError("Chat not found")
        return match

    def _file(self, chat_id: str) -> Path:
        return self.folder / (chat_id + ".jsonl")

    def list(self, chat_id: str, limit: int = 200) -> dict:
        chat = self._chat(chat_id)
        if not 1 <= limit <= 500:
            raise ValueError("Invalid message limit")
        path = self._file(chat_id)
        if not path.exists():
            return {"chat": chat, "messages": []}
        messages = []
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    item = json.loads(line)
                    if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
                        raise ValueError("Invalid Chat transcript")
                    messages.append(item)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Chat transcript is unreadable") from exc
        return {"chat": chat, "messages": messages[-limit:]}

    def _append_record(self, chat_id: str, text: str, role: str) -> dict:
        chat = self._chat(chat_id)
        if not chat["path_available"]:
            raise ValueError("Chat path unavailable; history is read-only")
        if chat.get("archived"):
            raise ValueError("Archived Chat is read-only")
        if role not in {"user", "assistant"}:
            raise ValueError("Invalid Chat message role")
        if not isinstance(text, str) or not text.strip() or len(text) > 20000:
            raise ValueError("Message must contain 1-20000 characters")
        record = {
            "message_id": uuid.uuid4().hex,
            "role": role,
            "text": text.strip(),
            "created_at": time.time(),
        }
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self._file(chat_id)
        with project_file_lock(path):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return record

    def append(self, chat_id: str, text: str, role: str = "user") -> dict:
        if role != "user":
            raise ValueError("Only user-authored messages can be appended through this API")
        return self._append_record(chat_id, text, "user")

    def append_assistant(self, chat_id: str, text: str) -> dict:
        """Internal-only assistant append used after a real backend response."""
        return self._append_record(chat_id, text, "assistant")
