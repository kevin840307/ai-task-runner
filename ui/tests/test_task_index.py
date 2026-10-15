"""Durable Task index regression tests."""
import tempfile
import unittest
from pathlib import Path

from ui.task_index import TaskIndex


class TaskIndexTests(unittest.TestCase):
    def test_history_survives_multiple_tasks_on_same_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            index = TaskIndex(Path(temp) / "tasks.json")
            first = index.create(chat_id="c1", root_path=str(root), instruction="first")
            second = index.create(chat_id="c1", root_path=str(root), instruction="second")
            self.assertNotEqual(first["task_id"], second["task_id"])
            self.assertEqual([x["title"] for x in index.list(chat_id="c1")], ["first", "second"])

    def test_execution_segments_append_without_overwriting_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            index = TaskIndex(Path(temp) / "tasks.json")
            task = index.create(chat_id="c1", root_path=str(root), instruction="work")
            index.append_execution(task["task_id"], {"request_id": "r1", "run_id": ""})
            index.append_execution(task["task_id"], {"request_id": "r2", "run_id": ""})
            rows = index.get(task["task_id"])["executions"]
            self.assertEqual([x["request_id"] for x in rows], ["r1", "r2"])

    def test_delete_is_explicit_per_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            index = TaskIndex(Path(temp) / "tasks.json")
            first = index.create(chat_id="c1", root_path=str(root), instruction="first")
            second = index.create(chat_id="c1", root_path=str(root), instruction="second")
            index.delete(first["task_id"])
            self.assertEqual([x["task_id"] for x in index.list()], [second["task_id"]])

    def test_invalid_index_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tasks.json"
            path.write_text("{broken", encoding="utf-8")
            index = TaskIndex(path)
            with self.assertRaisesRegex(ValueError, "unreadable"):
                index.list()
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


if __name__ == "__main__":
    unittest.main()
