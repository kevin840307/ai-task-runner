from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from ui.project_runtime_state import ProjectRuntimeMixin


class FakeRuntime(ProjectRuntimeMixin):
    def __init__(self):
        self._runtime_lock = threading.RLock()
        self.runtime = {
            "running": False,
            "completed": False,
            "stale": False,
            "actions": {"run": True, "resume": False},
        }
        self.calls = []

    def read_runtime(self, project: Path):
        return dict(self.runtime)

    def launch(self, project: Path, goal, **kwargs):
        self.calls.append((Path(project), goal, kwargs))

    def _reset_runtime_locked(self, project: Path):
        self.calls.append(("reset", Path(project)))
        return []


class TaskListRuntimeAdapterTests(unittest.TestCase):
    def test_task_list_delegates_to_canonical_launch_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            script = project / "tasks.yaml"
            script.write_text("- prompt: x\n  validator: ai\n", encoding="utf-8")
            state = FakeRuntime()

            state.launch_script_task(project, str(script), workflow="workflow.yaml", backend="fake", model="m")

            self.assertEqual(len(state.calls), 1)
            root, goal, kwargs = state.calls[0]
            self.assertEqual(root, project)
            self.assertIsNone(goal)
            self.assertEqual(kwargs["mode"], "run")
            self.assertEqual(kwargs["script_file"], str(script.resolve()))
            self.assertEqual(kwargs["workflow"], "workflow.yaml")

    def test_task_list_start_fails_closed_when_same_path_is_active(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            script = project / "tasks.yaml"
            script.write_text("- prompt: x\n  validator: ai\n", encoding="utf-8")
            state = FakeRuntime()
            state.runtime = {
                "running": True,
                "completed": False,
                "stale": False,
                "actions": {"run": False, "resume": False},
            }

            with self.assertRaisesRegex(ValueError, "already has an active runtime"):
                state.launch_script_task(project, str(script))

            self.assertEqual(state.calls, [])


if __name__ == "__main__":
    unittest.main()
