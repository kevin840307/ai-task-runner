"""Phase 1 Chat transcript persistence and isolation tests."""
import tempfile
import unittest
from pathlib import Path

from ui.chat_index import ChatIndex
from ui.chat_messages import ChatMessages


class ChatMessageTests(unittest.TestCase):
    def test_persistent_and_isolated_conversations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            index = ChatIndex(Path(temp) / "chats.json")
            first = index.create(str(root))["chat_id"]
            second = index.create(str(root))["chat_id"]
            messages = ChatMessages(Path(temp) / "messages", index)
            sent = messages.append(first, "Investigate startup")
            self.assertEqual(sent["role"], "user")
            self.assertEqual(ChatMessages(Path(temp) / "messages", ChatIndex(index.file)).list(first)["messages"][0]["text"], "Investigate startup")
            self.assertEqual(messages.list(second)["messages"], [])
            self.assertEqual(len(messages.list(first)["messages"]), 1)

    def test_missing_path_keeps_transcript_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            root.mkdir()
            index = ChatIndex(Path(temp) / "chats.json")
            chat_id = index.create(str(root))["chat_id"]
            messages = ChatMessages(Path(temp) / "messages", index)
            messages.append(chat_id, "hello")
            root.rmdir()
            result = messages.list(chat_id)
            self.assertFalse(result["chat"]["path_available"])
            self.assertEqual(result["messages"][0]["text"], "hello")
            with self.assertRaisesRegex(ValueError, "path unavailable"):
                messages.append(chat_id, "should fail")

    def test_rejects_unknown_chat_and_forged_assistant_message(self):
        with tempfile.TemporaryDirectory() as temp:
            index = ChatIndex(Path(temp) / "chats.json")
            messages = ChatMessages(Path(temp) / "messages", index)
            with self.assertRaisesRegex(ValueError, "not found"):
                messages.append("0" * 32, "hello")
            root = Path(temp) / "root"
            root.mkdir()
            chat_id = index.create(str(root))["chat_id"]
            with self.assertRaisesRegex(ValueError, "user-authored"):
                messages.append(chat_id, "fabricated response", role="assistant")
            with self.assertRaisesRegex(ValueError, "1-20000"):
                messages.append(chat_id, "")

    def test_archived_chat_is_read_only_at_storage_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            root.mkdir()
            index = ChatIndex(Path(temp) / "chats.json")
            chat_id = index.create(str(root))["chat_id"]
            messages = ChatMessages(Path(temp) / "messages", index)
            messages.append(chat_id, "before archive")
            index.update(chat_id, archived=True)
            self.assertEqual(messages.list(chat_id)["messages"][0]["text"], "before archive")
            with self.assertRaisesRegex(ValueError, "Archived Chat is read-only"):
                messages.append(chat_id, "after archive")

    def test_rejects_invalid_identity_and_bounds(self):
        with tempfile.TemporaryDirectory() as temp:
            index = ChatIndex(Path(temp) / "chats.json")
            messages = ChatMessages(Path(temp) / "messages", index)
            with self.assertRaisesRegex(ValueError, "identity"):
                messages.list("../../etc/passwd")
            root = Path(temp) / "root"
            root.mkdir()
            chat_id = index.create(str(root))["chat_id"]
            with self.assertRaisesRegex(ValueError, "limit"):
                messages.list(chat_id, limit=501)


if __name__ == "__main__":
    unittest.main()
