from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from ui.chat_index import ChatIndex
from ui.task_index import TaskIndex
from ui.task_workspace_state import TaskWorkspaceMixin


class FakeTaskWorkspace(TaskWorkspaceMixin):
    def __init__(self, root: Path):
        self.repo_root = root
        self.tasks = TaskIndex(root / "tasks.json")
        self.chats = ChatIndex(root / "chats.json")
        self.runtime = {
            "running": False,
            "completed": True,
            "status": "completed",
            "stage": "completed",
            "cycle": 2,
            "completed_count": 1,
            "total": 1,
            "last_error": "",
            "stream": "final visible output",
            "activity_summary": ["Validated"],
            "recovery": {},
            "actions": {"run": True, "rerun": True, "stop": False, "resume": False},
            "run_id": "run-old",
            "request_id": "req-old",
        }
        self.launched = []

    @staticmethod
    def _read_json(path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _read_text(path: Path, limit: int = 0):
        try:
            value = path.read_text(encoding="utf-8")
        except OSError:
            return ""
        return value[-limit:] if limit else value

    def read_runtime(self, project: Path):
        return dict(self.runtime)

    def messages(self, project: Path):
        return []

    def sync_completion(self, project: Path):
        return False

    def _known_workflow_paths(self, project: Path):
        return [self.workflow]

    def product_defaults(self):
        return {"default_workflow": self.workflow.name}

    def studio_files(self, project: Path):
        return {
            "workflows": [{
                "name": self.workflow.name,
                "path": str(self.workflow.resolve()),
                "hidden": False,
            }],
            "prompts": [],
        }

    @staticmethod
    def _activity_summary(stream):
        return [line for line in str(stream or "").splitlines() if line][-20:]

    @staticmethod
    def _display_stream(stream):
        return str(stream or "")

    def launch_message(self, project: Path, message: str, **kwargs):
        self.launched.append((Path(project), message, kwargs))
        return {
            "request_id": "req-new",
            "workflow": kwargs.get("workflow", ""),
            "backend": kwargs.get("backend", ""),
            "model": kwargs.get("model", ""),
        }


class TaskWorkspaceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.state = FakeTaskWorkspace(self.root)
        self.state.workflow = self.root / "workflow.yaml"
        self.state.workflow.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        self.chat_id = self.state.chats.create(str(self.project))["chat_id"]

    def tearDown(self):
        self.temp.cleanup()

    def _completed_task(self):
        task = self.state.tasks.create(
            chat_id=self.chat_id,
            root_path=str(self.project),
            instruction="original frozen instruction",
            workflow=str(self.state.workflow),
        )
        task = self.state.tasks.update(
            task["task_id"],
            last_status="completed",
            backend="qwen",
            model="model-a",
        )
        task = self.state.tasks.append_execution(task["task_id"], {
            "request_id": "req-old",
            "run_id": "run-old",
            "instruction": task["instruction"],
            "workflow": str(self.state.workflow),
        })
        return self.state.tasks.update(task["task_id"], last_status="completed")

    def test_task_list_payload_is_bounded_summary_not_full_history(self):
        task = self.state.tasks.create(
            chat_id=self.chat_id,
            root_path=str(self.project),
            instruction="x" * 5000,
            workflow=str(self.state.workflow),
        )
        task = self.state.tasks.append_execution(task["task_id"], {
            "request_id": "req-summary",
            "run_id": "run-summary",
            "started_at": 123.0,
            "instruction": "y" * 5000,
            "workflow": str(self.state.workflow),
            "evidence": {"stream_tail": "z" * 6000},
        })
        payload = self.state.tasks_payload(self.chat_id)
        summary = payload["tasks"][0]

        self.assertNotIn("executions", summary)
        self.assertNotIn("items", summary)
        self.assertNotIn("instruction", summary)
        self.assertEqual(summary["latest_execution_started_at"], 123.0)
        self.assertEqual(summary["execution_count"], 1)
        self.assertNotIn("stream", summary.get("runtime") or {})

        detail = self.state.task_detail(task["task_id"])
        self.assertEqual(detail["executions"][0]["run_id"], "run-summary")
        self.assertEqual(detail["instruction"], "x" * 5000)

    def test_task_history_limit_can_extend_beyond_legacy_500_cap(self):
        task = self.state.tasks.create(
            chat_id=self.chat_id,
            root_path=str(self.project),
            instruction="history",
            workflow=str(self.state.workflow),
        )
        payload = self.state.tasks_payload(self.chat_id, limit=501)
        self.assertEqual(payload["tasks"][0]["task_id"], task["task_id"])
        self.assertFalse(payload["meta"]["has_more"])

    def test_explicit_and_default_workflows_use_same_allowed_catalog(self):
        self.assertEqual(
            self.state._resolve_task_workflow(self.project, str(self.state.workflow)),
            str(self.state.workflow.resolve()),
        )
        self.assertEqual(
            self.state._resolve_task_workflow(self.project, ""),
            str(self.state.workflow.resolve()),
        )

    def test_historical_completed_task_reruns_from_its_frozen_inputs_when_path_is_free(self):
        task = self._completed_task()
        # Another terminal Task may be the latest runtime owner; this Task is history.
        marker = self.project / ".ai-task-runner" / "ui" / "active-task.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"task_id": "f" * 32, "request_id": "other"}), encoding="utf-8")

        detail = self.state.task_detail(task["task_id"])
        self.assertTrue(detail["available_actions"]["rerun"])

        result = self.state.task_action(task["task_id"], "rerun")

        self.assertEqual(len(result["executions"]), 2)
        launched_project, message, kwargs = self.state.launched[-1]
        self.assertEqual(launched_project, self.project)
        self.assertEqual(message, "original frozen instruction")
        self.assertEqual(kwargs["workflow"], str(self.state.workflow))
        self.assertEqual(kwargs["backend"], "qwen")
        self.assertEqual(kwargs["model"], "model-a")
        marker_value = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(marker_value["task_id"], task["task_id"])

    def test_delete_removes_only_task_owned_ui_artifacts(self):
        task = self._completed_task()
        request_dir = self.project / ".ai-task-runner" / "ui" / "requests" / "req-old"
        request_dir.mkdir(parents=True)
        (request_dir / "request.json").write_text("{}", encoding="utf-8")
        list_dir = self.project / ".ai-task-runner" / "ui" / "task-lists"
        list_dir.mkdir(parents=True)
        script = list_dir / f"{task['task_id']}-001.yaml"
        script.write_text("- prompt: x\n", encoding="utf-8")
        archive = self.project / ".ai-task-runner" / "ui" / "task-history" / task["task_id"] / "runtime"
        archive.mkdir(parents=True)
        (archive / "state.json").write_text("{}", encoding="utf-8")
        source_file = self.project / "keep.txt"
        source_file.write_text("keep", encoding="utf-8")

        self.state.runtime = {
            "running": False,
            "completed": True,
            "status": "completed",
            "actions": {"run": True, "rerun": True, "stop": False, "resume": False},
        }
        self.state.delete_task(task["task_id"])

        self.assertFalse(request_dir.exists())
        self.assertFalse(script.exists())
        self.assertFalse(archive.parent.exists())
        self.assertTrue(source_file.is_file())
        with self.assertRaisesRegex(ValueError, "Task not found"):
            self.state.tasks.get(task["task_id"])

    def test_task_list_launch_failure_preserves_frozen_parent_inputs(self):
        items = [
            {"instruction": "first", "workflow": "", "raw": {"prompt": "first"}},
            {"instruction": "second", "workflow": "", "raw": {"prompt": "second"}},
        ]
        with patch.object(
            self.state,
            "launch_script_task",
            side_effect=ValueError("temporary launch failure"),
        ):
            task = self.state.create_task_list(
                chat_id=self.chat_id,
                items=items,
                default_workflow=str(self.state.workflow),
                backend="qwen",
                model="model-a",
            )

        self.assertEqual(task["last_status"], "needs_attention")
        self.assertEqual(task["workflow"], str(self.state.workflow))
        self.assertEqual(task["backend"], "qwen")
        self.assertEqual(task["model"], "model-a")
        self.assertEqual(
            [item["instruction"] for item in task["items"]],
            ["first", "second"],
        )

    def test_sequential_rerun_uses_original_frozen_items_not_latest_continue_segment(self):
        frozen_items = [
            {"instruction": "first", "workflow": "", "raw": {"prompt": "first"}},
            {"instruction": "second", "workflow": "", "raw": {"prompt": "second"}},
        ]
        task = self.state.tasks.create(
            chat_id=self.chat_id,
            root_path=str(self.project),
            instruction="Task List · 2 items",
            task_type="sequential",
            workflow=str(self.state.workflow),
        )
        task = self.state.tasks.update(
            task["task_id"],
            items=frozen_items,
            backend="qwen",
            model="model-a",
            last_status="completed",
        )
        task = self.state.tasks.append_execution(task["task_id"], {
            "request_id": "",
            "script_file": str(self.project / "original.yaml"),
            "instruction": task["instruction"],
            "workflow": str(self.state.workflow),
            "default_workflow": str(self.state.workflow),
            "run_id": "",
            "item_count": 2,
        })
        task = self.state.tasks.append_execution(task["task_id"], {
            "request_id": "",
            "script_file": str(self.project / "continue.yaml"),
            "instruction": "follow-up",
            "workflow": str(self.state.workflow),
            "default_workflow": str(self.state.workflow),
            "run_id": "",
            "item_count": 1,
        })
        task = self.state.tasks.update(task["task_id"], last_status="completed")
        marker = self.project / ".ai-task-runner" / "ui" / "active-task.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps({"task_id": "f" * 32, "request_id": "other"}),
            encoding="utf-8",
        )
        rerun_script = self.project / "rerun.yaml"
        rerun_script.write_text("- prompt: first\n- prompt: second\n", encoding="utf-8")

        with patch.object(
            self.state,
            "_write_task_list",
            return_value=rerun_script,
        ) as write_list, patch.object(self.state, "launch_script_task") as launch:
            result = self.state.task_action(task["task_id"], "rerun")

        write_list.assert_called_once_with(
            self.project,
            task["task_id"],
            frozen_items,
            3,
        )
        launch.assert_called_once_with(
            self.project,
            str(rerun_script),
            workflow=str(self.state.workflow),
            backend="qwen",
            model="model-a",
        )
        latest = result["executions"][-1]
        self.assertEqual(latest["script_file"], str(rerun_script))
        self.assertEqual(latest["item_count"], 2)
        self.assertEqual(latest["instruction"], "Task List · 2 items")


    def test_historical_sequential_task_keeps_child_evidence_after_new_runtime_owner(self):
        task = self.state.tasks.create(
            chat_id=self.chat_id,
            root_path=str(self.project),
            instruction="Task List · 2 items",
            task_type="sequential",
            workflow=str(self.state.workflow),
        )
        task = self.state.tasks.append_execution(task["task_id"], {
            "request_id": "req-list",
            "script_file": str(self.project / ".ai-task-runner" / "ui" / "task-lists" / "list.yaml"),
            "instruction": task["instruction"],
            "workflow": str(self.state.workflow),
            "run_id": "",
        })
        marker = self.project / ".ai-task-runner" / "ui" / "active-task.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps({"task_id": task["task_id"], "request_id": "req-list"}),
            encoding="utf-8",
        )
        script_root = self.project / ".ai-task-runner" / "script"
        for index, run_id, result in (
            (1, "child-one", "one result"),
            (2, "child-two", "two result"),
        ):
            child = script_root / f"{index:03d}"
            (child / "debug").mkdir(parents=True)
            (child / "state.json").write_text(
                json.dumps({
                    "run_id": run_id,
                    "completed": True,
                    "stage": "completed",
                    "last_error": "",
                }),
                encoding="utf-8",
            )
            (child / "debug" / "last-result.txt").write_text(result, encoding="utf-8")
        self.state.runtime = {
            **self.state.runtime,
            "request_id": "req-list",
            "completed": True,
            "running": False,
            "status": "completed",
            "script_index": 2,
            "script_total": 2,
        }

        synced = self.state._sync_task(task)
        self.assertEqual(
            [child["run_id"] for child in synced["executions"][-1]["children"]],
            ["child-one", "child-two"],
        )

        marker.write_text(
            json.dumps({"task_id": "f" * 32, "request_id": "new-runtime"}),
            encoding="utf-8",
        )
        historical = self.state.task_detail(task["task_id"])

        self.assertIsNone(historical["runtime"])
        self.assertEqual(
            [child["result"] for child in historical["executions"][-1]["children"]],
            ["one result", "two result"],
        )


    def test_failed_worktree_cleanup_keeps_archived_history_pointer(self):
        source = self.root / "source"
        source.mkdir()
        workspace = self.root / "worktree"
        workspace.mkdir()
        runtime = workspace / ".ai-task-runner"
        runtime.mkdir()
        (runtime / "state.json").write_text("{}", encoding="utf-8")
        task = self.state.tasks.create(
            chat_id=self.chat_id,
            root_path=str(workspace),
            instruction="done in isolated workspace",
            workflow=str(self.state.workflow),
        )
        task = self.state.tasks.update(
            task["task_id"],
            source_root_path=str(source),
            workspace_kind="worktree",
            workspace_managed=True,
            last_status="completed",
        )
        archive = source / ".ai-task-runner" / "ui" / "task-history" / task["task_id"] / "runtime"

        def fake_archive(worktree, target):
            self.assertEqual(Path(worktree), workspace)
            self.assertEqual(Path(target), archive)
            target.mkdir(parents=True)
            (target / "state.json").write_text("{}", encoding="utf-8")
            return str(target)

        with patch("ui.task_workspace_state.archive_runtime", side_effect=fake_archive), patch(
            "ui.task_workspace_state.remove_task_worktree",
            side_effect=ValueError("dirty worktree"),
        ):
            with self.assertRaisesRegex(ValueError, "dirty worktree"):
                self.state.cleanup_task_workspace(task["task_id"])

        persisted = self.state.tasks.get(task["task_id"])
        self.assertEqual(persisted["runtime_archive"], str(archive))
        self.assertFalse(persisted.get("workspace_removed", False))
        self.assertTrue((archive / "state.json").is_file())


    def test_terminal_execution_evidence_is_persisted_before_future_runtime_reuse(self):
        task = self._completed_task()
        marker = self.project / ".ai-task-runner" / "ui" / "active-task.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(
            json.dumps({"task_id": task["task_id"], "request_id": "req-old"}),
            encoding="utf-8",
        )
        result_file = self.project / ".ai-task-runner" / "debug" / "last-result.txt"
        result_file.parent.mkdir(parents=True)
        result_file.write_text("durable final result", encoding="utf-8")

        synced = self.state._sync_task(task)
        evidence = synced["executions"][-1]["evidence"]

        self.assertEqual(evidence["result"], "durable final result")
        self.assertEqual(evidence["stream_tail"], "final visible output")
        self.assertEqual(evidence["stage"], "completed")
        self.assertEqual(evidence["activity_summary"], ["Validated"])


if __name__ == "__main__":
    unittest.main()
