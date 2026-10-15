from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ui.chat_index import ChatIndex
from ui.chat_workspace_state import ChatWorkspaceMixin
from ui.task_index import TaskIndex


class FakeChatWorkspace(ChatWorkspaceMixin):
    def __init__(self, root: Path):
        self.repo_root = root
        self.chats = ChatIndex(root / "chats.json")
        self.tasks = TaskIndex(root / "tasks.json")
        self.runtime_by_task: dict[str, dict | None] = {}

    def _sync_task(self, task: dict) -> dict:
        return {**task, "runtime": self.runtime_by_task.get(task["task_id"])}


class ChatWorkspaceStateTests(unittest.TestCase):
    def test_archive_allows_inactive_historical_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            state = FakeChatWorkspace(root)
            chat = state.chats.create(str(project))
            task = state.tasks.create(
                chat_id=chat["chat_id"],
                root_path=str(project),
                instruction="done",
            )
            state.runtime_by_task[task["task_id"]] = None

            archived = state.archive_chat(chat["chat_id"], True)

            self.assertTrue(archived["archived"])

    def test_archive_blocks_matched_active_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            state = FakeChatWorkspace(root)
            chat = state.chats.create(str(project))
            task = state.tasks.create(
                chat_id=chat["chat_id"],
                root_path=str(project),
                instruction="running",
            )
            state.runtime_by_task[task["task_id"]] = {"running": True}

            with self.assertRaisesRegex(ValueError, "Stop the active Task"):
                state.archive_chat(chat["chat_id"], True)
            self.assertFalse(state.chats.list()[0].get("archived", False))


if __name__ == "__main__":
    unittest.main()
