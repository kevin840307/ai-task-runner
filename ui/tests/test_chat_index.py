"""Regression coverage for future Phase 1 Chat identity (no Runner state involved)."""
import json
import tempfile
import unittest

import pytest
from pathlib import Path

from ui.chat_index import ChatIndex


class ChatIndexTests(unittest.TestCase):
    def test_multiple_chats_per_path_and_persistent_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            file = Path(temp) / "ui" / "chats.json"
            index = ChatIndex(file)
            first = index.create(str(root), "First")
            second = index.create(str(root), "Second")
            self.assertNotEqual(first["chat_id"], second["chat_id"])
            self.assertEqual([x["chat_id"] for x in ChatIndex(file).list(str(root))],
                             [first["chat_id"], second["chat_id"]])
            self.assertEqual(first["root_path"], str(root.resolve()))
            self.assertNotIn("workflow", first)
            self.assertNotIn("run_id", first)

    def test_missing_path_retains_history_and_cannot_create(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            index = ChatIndex(Path(temp) / "chats.json")
            created = index.create(str(root))
            root.rmdir()
            self.assertEqual(index.list()[0]["chat_id"], created["chat_id"])
            self.assertFalse(index.list()[0]["path_available"])
            with self.assertRaisesRegex(ValueError, "does not exist"):
                index.create(str(root))

    def test_invalid_existing_index_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "chats.json"
            file.write_text("{broken", encoding="utf-8")
            root = Path(temp) / "root"
            root.mkdir()
            with self.assertRaisesRegex(ValueError, "unreadable"):
                ChatIndex(file).create(str(root))
            self.assertEqual(file.read_text(encoding="utf-8"), "{broken")

    def test_path_filter(self):
        with tempfile.TemporaryDirectory() as temp:
            a, b = Path(temp) / "a", Path(temp) / "b"
            a.mkdir()
            b.mkdir()
            index = ChatIndex(Path(temp) / "chats.json")
            index.create(str(a), "A")
            index.create(str(b), "B")
            self.assertEqual([x["title"] for x in index.list(str(a))], ["A"])

    def test_invalid_title_rejected_without_write(self):
        with tempfile.TemporaryDirectory() as temp:
            index = ChatIndex(Path(temp) / "chats.json")
            with self.assertRaisesRegex(ValueError, "too long"):
                index.create(temp, "X" * 121)
            self.assertFalse(index.file.exists())


if __name__ == "__main__":
    unittest.main()


def test_structurally_invalid_identity_records_fail_closed(tmp_path):
    index_file = tmp_path / "chats.json"
    index_file.write_text(
        json.dumps([{"chat_id": "abc", "title": "missing root"}]),
        encoding="utf-8",
    )
    index = ChatIndex(index_file)
    with pytest.raises(ValueError, match="root_path"):
        index.list()

    index_file.write_text(
        json.dumps([
            {"chat_id": "dup", "root_path": str(tmp_path)},
            {"chat_id": "dup", "root_path": str(tmp_path)},
        ]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate chat_id"):
        index.list()
