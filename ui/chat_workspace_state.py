"""Normal project Chat turns over the canonical backend adapter."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


class ChatWorkspaceMixin:
    def _chat_record(self, chat_id: str) -> dict:
        chat = next((row for row in self.chats.list() if row.get("chat_id") == chat_id), None)
        if chat is None:
            raise ValueError("Chat not found")
        return chat

    def suggest_task_list(self, chat_id: str, request_text: str) -> dict:
        chat = self._chat_record(chat_id)
        if chat.get("archived"):
            raise ValueError("Archived Chat is read-only")
        if not chat.get("path_available"):
            raise ValueError("Chat path unavailable")
        text = str(request_text or "").strip()
        if not text:
            raise ValueError("Task List request is empty")
        history = self.chat_messages.list(chat_id, limit=30)["messages"]
        command = [
            sys.executable,
            str(self.repo_root / "tool" / "task_list_suggest.py"),
            "--project-root",
            str(chat["root_path"]),
        ]
        backend = str(chat.get("backend") or "")
        model = str(chat.get("model") or "")
        if backend:
            command += ["--backend", backend]
        if model:
            command += ["--model", model]
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.repo_root),
                input=json.dumps({"request": text, "history": history}, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=210,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Task List suggestion unavailable: {exc}") from exc
        try:
            payload = json.loads((completed.stdout or "").strip())
        except json.JSONDecodeError as exc:
            detail = (completed.stderr or completed.stdout or "No output")[-2000:]
            raise ValueError(f"Task List suggestion returned invalid output: {detail}") from exc
        if completed.returncode != 0 or payload.get("error"):
            raise ValueError(str(payload.get("error") or "Task List suggestion failed"))
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("Task List suggestion returned no items")
        return {"items": items}

    def archive_chat(self, chat_id: str, archived: bool = True) -> dict:
        chat = self._chat_record(chat_id)
        if archived:
            for task in self.tasks.list(chat_id=chat_id):
                current = self._sync_task(task)
                runtime = current.get("runtime")
                if isinstance(runtime, dict) and runtime.get("running"):
                    raise ValueError("Stop the active Task before archiving this Chat")
        return self.chats.update(chat_id, archived=bool(archived))

    def chat_turn(self, chat_id: str, message: str) -> dict:
        text = str(message or "").strip()
        if not text:
            raise ValueError("Chat message is empty")
        if len(text) > 20_000:
            raise ValueError("Chat message is too long")
        with self._conversation_lock:
            chat = self._chat_record(chat_id)
            if chat.get("archived"):
                raise ValueError("Archived Chat is read-only")
            if not chat.get("path_available"):
                raise ValueError("Chat path unavailable; history is read-only")
            project = Path(chat["root_path"])
            history = self.chat_messages.list(chat_id, limit=40)["messages"]
            command = [
                sys.executable,
                str(self.repo_root / "tool" / "chat_turn.py"),
                "--project-root",
                str(project),
            ]
            backend = str(chat.get("backend") or "")
            model = str(chat.get("model") or "")
            session_id = str(chat.get("session_id") or "")
            if backend:
                command += ["--backend", backend]
            if model:
                command += ["--model", model]
            if session_id:
                command += ["--session-id", session_id]
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(self.repo_root),
                    input=json.dumps({"message": text, "history": history}, ensure_ascii=False),
                    capture_output=True,
                    text=True,
                    timeout=210,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ValueError(f"Chat backend unavailable: {exc}") from exc
            try:
                payload = json.loads((completed.stdout or "").strip())
            except json.JSONDecodeError as exc:
                detail = (completed.stderr or completed.stdout or "No output")[-2000:]
                raise ValueError(f"Chat backend returned invalid output: {detail}") from exc
            if completed.returncode != 0 or payload.get("error"):
                raise ValueError(str(payload.get("error") or "Chat backend failed"))
            answer = str(payload.get("text") or "").strip()
            if not answer:
                raise ValueError("Chat backend returned an empty response")
            user = self.chat_messages.append(chat_id, text)
            assistant = self.chat_messages.append_assistant(chat_id, answer)
            updated = self.chats.update(
                chat_id,
                session_id=str(payload.get("session_id") or ""),
                backend=str(payload.get("backend") or backend),
                model=str(payload.get("model") or model),
            )
            return {"chat": updated, "user": user, "assistant": assistant}
